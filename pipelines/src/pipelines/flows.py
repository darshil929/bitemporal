"""Runs the history bootstrap or the daily sync and reports what each source did.

    python -m pipelines.flows bootstrap [--from DAY --to DAY]
    python -m pipelines.flows sync [--day DAY | --from DAY --to DAY]

The bootstrap reads the two most recent years first, so the platform is usable before the older
years arrive, and those in a second run. The sync reads the seven days ending on its day, today in
India by default, so a file published late is asked for again. A flow finishes whatever a source
answers; the launcher exits 1 where a day, a check or a step failed, and 2 where it did not start.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from dagster import (
    DagsterInstance,
    DagsterRunStatus,
    JobDefinition,
    RunsFilter,
    execute_job,
    reconstructable,
)

from pipelines.assets.ingestion.calendar import INGESTION_DAYS
from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.config.settings import DatabaseSettings
from pipelines.definitions import defs
from pipelines.jobs import BOOTSTRAP, FLOW_TAG, RANGE_END, RANGE_START, SYNC, sync_window
from pipelines.resources import Database

RECENT = timedelta(days=730)

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

UNFINISHED = [DagsterRunStatus.QUEUED, DagsterRunStatus.STARTING, DagsterRunStatus.STARTED]

# The counts each source's result carries: days for prices and delivery, years of ex-dates for
# corporate actions.
SOURCE_COUNTS = {
    "bse_bhavcopy": ("published", "unpublished", "outside_coverage", "failed"),
    "nse_bhavcopy": ("published", "unpublished", "outside_coverage", "failed"),
    "bse_delivery": ("published", "unpublished", "outside_coverage", "failed"),
    "nse_delivery": ("published", "unpublished", "outside_coverage", "failed"),
    "corporate_actions": ("ranges", "failed"),
    "nse_corporate_actions": ("ranges", "failed"),
}

FAILED_ATTEMPTS = """
select source_id, partition_key, detail
from ingestion_log
where outcome = 'failed' and fetched_at between %s and %s
order by source_id, partition_key
"""


class FlowRefused(Exception):
    """A flow cannot start against the database or the Dagster instance as they stand."""


def history_bootstrap() -> JobDefinition:
    return defs.resolve_job_def("history_bootstrap")


def daily_sync() -> JobDefinition:
    return defs.resolve_job_def("daily_sync")


def bootstrap_windows(today: date) -> list[tuple[date, date]]:
    """The two most recent years ending today, then every earlier day of the calendar."""
    split = today - RECENT
    return [(split + timedelta(days=1), today), (INGESTION_DAYS.start.date(), split)]


def refuse_unless_ready(connection: psycopg.Connection, instance: DagsterInstance) -> None:
    """Refuse a database behind the latest migration, and a second flow while one is running."""
    head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
    current = None
    table = connection.execute("select to_regclass('alembic_version')").fetchone()
    if table is not None and table[0] is not None:
        version = connection.execute("select version_num from alembic_version").fetchone()
        current = version[0] if version else None
    if current != head:
        raise FlowRefused(f"the database is at migration {current}, not {head}: run make migrate")

    running = instance.get_runs(RunsFilter(tags={FLOW_TAG: [BOOTSTRAP, SYNC]}, statuses=UNFINISHED))
    if running:
        raise FlowRefused(f"flow run {running[0].run_id} is {running[0].status.value}")


@dataclass
class FlowReport:
    """What one run of a flow did, source by source."""

    first: date
    last: date
    counts: dict[str, dict[str, int]]
    failures: list[tuple[str, str, str]]
    checks_passed: int
    failed_checks: list[str]
    failed_steps: list[str]
    unmaterialized: list[str]

    @property
    def is_clean(self) -> bool:
        return not (
            self.failures
            or self.failed_checks
            or self.failed_steps
            or self.unmaterialized
            or any(counts.get("failed") for counts in self.counts.values())
        )

    def lines(self) -> list[str]:
        shown = [f"{self.first} to {self.last}"]
        for source, fields in SOURCE_COUNTS.items():
            counts = self.counts.get(source)
            read = "not run" if counts is None else "  ".join(f"{f} {counts[f]}" for f in fields)
            shown.append(f"  {source:<22} {read}")
        shown += [f"  failed {source} {key}: {detail}" for source, key, detail in self.failures]
        shown.append(f"  checks {self.checks_passed} passed, {len(self.failed_checks)} failed")
        shown += [f"  check failed: {name}" for name in self.failed_checks]
        shown += [f"  step failed: {name}" for name in self.failed_steps]
        shown += [f"  not materialized: {name}" for name in self.unmaterialized]
        return shown


def run_window(
    instance: DagsterInstance, job: Callable[[], JobDefinition], first: date, last: date
) -> FlowReport:
    tags = {RANGE_START: first.isoformat(), RANGE_END: last.isoformat()}
    with execute_job(reconstructable(job), instance=instance, tags=tags) as result:
        counts = {
            event.asset_key.to_user_string(): {
                name: int(value.value)
                for name, value in event.materialization.metadata.items()
                if isinstance(value.value, int)
            }
            for event in result.get_asset_materialization_events()
            if event.asset_key is not None and event.materialization is not None
        }
        planned = {key.to_user_string() for key in job().asset_layer.selected_asset_keys}
        checks = result.get_asset_check_evaluations()
        failed_steps = sorted(result.get_failed_step_keys())
        run_id = result.run_id

    record = instance.get_run_record_by_id(run_id)
    started = datetime.fromtimestamp(record.start_time or 0, UTC) if record else datetime.now(UTC)
    ended = datetime.fromtimestamp(record.end_time or 0, UTC) if record else datetime.now(UTC)
    with Database().connect() as connection:
        failures = [
            (source, key, detail or "")
            for source, key, detail in connection.execute(FAILED_ATTEMPTS, (started, ended))
        ]

    return FlowReport(
        first=first,
        last=last,
        counts=counts,
        failures=failures,
        checks_passed=sum(1 for check in checks if check.passed),
        failed_checks=sorted(check.check_name for check in checks if not check.passed),
        failed_steps=failed_steps,
        unmaterialized=sorted(planned - set(counts)),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipelines.flows")
    parser.add_argument("flow", choices=(BOOTSTRAP, SYNC))
    parser.add_argument("--from", dest="first", type=date.fromisoformat)
    parser.add_argument("--to", dest="last", type=date.fromisoformat)
    parser.add_argument("--day", type=date.fromisoformat, help="a sync's last day, today if unset")
    args = parser.parse_args(argv)
    if (args.first is None) != (args.last is None) or (args.day and args.flow == BOOTSTRAP):
        parser.error("--from and --to go together, and --day belongs to a sync")

    today = datetime.now(VENUE_TIME).date()
    if args.first is not None:
        windows = [(args.first, args.last)]
    elif args.flow == BOOTSTRAP:
        windows = bootstrap_windows(today)
    else:
        windows = [sync_window(args.day or today)]
    job = history_bootstrap if args.flow == BOOTSTRAP else daily_sync

    settings = DatabaseSettings()
    target = urlsplit(settings.database_url)
    instance = DagsterInstance.get()
    print(f"database {target.path.lstrip('/')} on {target.hostname}:{target.port}", end=", ")
    print(f"schema {settings.schema_name}, Dagster instance {instance.root_directory}")
    try:
        with Database().connect() as connection:
            refuse_unless_ready(connection, instance)
    except FlowRefused as refusal:
        print(f"{args.flow} not started: {refusal}", file=sys.stderr)
        return 2

    reports = [run_window(instance, job, first, last) for first, last in windows]
    for report in reports:
        print("\n".join(report.lines()))
    return 0 if all(report.is_clean for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
