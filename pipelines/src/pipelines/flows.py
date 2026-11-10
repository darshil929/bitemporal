"""Runs the history bootstrap or the daily sync and reports what each source did.

    python -m pipelines.flows bootstrap [--from DAY --to DAY]
    python -m pipelines.flows sync [--day DAY | --from DAY --to DAY]

The bootstrap reads the two most recent years first, so the platform is usable before the older
years arrive, and those in a second run. The sync reads the seven days ending on its day, today in
India by default, so a file published late is asked for again. A flow finishes whatever a source
answers; the launcher exits 1 where a day, a check or a step failed, and 2 where it did not start.
A check of warning severity that does not pass is reported with the rows it found and fails nothing.

The terminal shows where the flow writes and each run's report. Everything a run prints, Dagster's
step log and dbt's output among it, goes to a file in the Dagster instance's `flow-logs` folder, or
to the terminal with `--verbose`. Once a run finishes, the database records it with its report and
steps, together with any finished run of either flow it has not yet recorded.
"""

import argparse
import contextlib
import os
import sys
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from dagster import (
    AssetCheckEvaluation,
    AssetCheckSeverity,
    DagsterEventType,
    DagsterInstance,
    DagsterRunStatus,
    Definitions,
    EventLogEntry,
    JobDefinition,
    RunRecord,
    RunsFilter,
    execute_job,
    reconstructable,
)
from psycopg.types.json import Jsonb

from pipelines.assets.ingestion.calendar import INGESTION_DAYS
from pipelines.assets.ingestion.corporate_actions import VENUE_TIME
from pipelines.config.settings import DatabaseSettings
from pipelines.jobs import BOOTSTRAP, FLOW_TAG, RANGE_END, RANGE_START, SYNC, sync_window
from pipelines.resources import Database

RECENT = timedelta(days=730)

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

UNFINISHED = [DagsterRunStatus.QUEUED, DagsterRunStatus.STARTING, DagsterRunStatus.STARTED]
FINISHED = [DagsterRunStatus.SUCCESS, DagsterRunStatus.FAILURE, DagsterRunStatus.CANCELED]

# The schema a run writes to, by which a database recognises its own runs in a shared instance.
SCHEMA_TAG = "bitemporal/schema"

STEP_ENDS = {
    DagsterEventType.STEP_SUCCESS: "succeeded",
    DagsterEventType.STEP_FAILURE: "failed",
    DagsterEventType.STEP_SKIPPED: "skipped",
}

# Dagster keeps its own telemetry in the instance's `logs` folder.
LOG_FOLDER = "flow-logs"

# The counts each source's result carries: days for prices and delivery, with the days asked for
# again and answered, the rows a corrected file changed and the days that could not be asked for
# again; years of ex-dates for corporate actions, with the stored actions an answer left out for
# instruments the venue no longer trades and the stored texts it replaced with others; statuses for
# a list of securities. A run from before a count existed shows it as a dash.
DAY_COUNTS = (
    "published",
    "unpublished",
    "outside_coverage",
    "failed",
    "rechecked",
    "corrected",
    "recheck_failed",
)
SOURCE_COUNTS = {
    "bse_bhavcopy": DAY_COUNTS,
    "nse_bhavcopy": DAY_COUNTS,
    "bse_delivery": DAY_COUNTS,
    "nse_delivery": DAY_COUNTS,
    "corporate_actions": ("ranges", "failed", "excused", "withdrawn"),
    "nse_corporate_actions": ("ranges", "failed", "excused", "withdrawn"),
    "bse_instrument_names": ("lists", "failed"),
    "nse_instrument_names": ("lists", "failed"),
}

# The rows a dbt test returned, as dagster-dbt records them on the check's evaluation.
ROWS_FOUND = "dagster_dbt/failed_row_count"

# dbt names each session it opens and heads each query with the target it builds, so a build still
# writing to the database shows there whichever process started it.
DBT_SESSIONS = """
select pid from pg_stat_activity
where datname = current_database() and application_name = 'dbt' and query like %s
order by pid
"""

FAILED_ATTEMPTS = """
select source_id, partition_key, detail
from ingestion_log
where outcome = 'failed' and fetched_at between %s and %s
order by source_id, partition_key
"""

FETCHED_DURING = "select exists (select from ingestion_log where fetched_at between %s and %s)"

RECORDED = "select run_id from flow_run where run_id = any(%s)"

RECORD_RUN = """
insert into flow_run (
    run_id, flow, first_day, last_day, started_at, ended_at, outcome, counts, checks_passed,
    failures, warned_checks, failed_checks, failed_steps, unmaterialized
) values (
    %(run_id)s, %(flow)s, %(first_day)s, %(last_day)s, %(started_at)s, %(ended_at)s, %(outcome)s,
    %(counts)s, %(checks_passed)s, %(failures)s, %(warned_checks)s, %(failed_checks)s,
    %(failed_steps)s, %(unmaterialized)s
)
"""

RECORD_STEP = (
    "insert into flow_run_step (run_id, step, started_at, ended_at, outcome)"
    " values (%s, %s, %s, %s, %s)"
)


class FlowRefused(Exception):
    """A flow cannot start against the database or the Dagster instance as they stand."""


def definitions() -> Definitions:
    # Building the definitions builds every asset, and Dagster warns about the beta parameters
    # some of them take. Built on first use, the warnings land in the run's output.
    from pipelines.definitions import defs

    return defs


def history_bootstrap() -> JobDefinition:
    return definitions().resolve_job_def("history_bootstrap")


def daily_sync() -> JobDefinition:
    return definitions().resolve_job_def("daily_sync")


@contextlib.contextmanager
def output_to(path: Path) -> Iterator[None]:
    """Send what this process and every process it starts write to the terminal into `path`.

    A run's steps execute in child processes, which inherit the descriptors rather than
    `sys.stdout`, so the descriptors are redirected as well as this process's streams.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()
    terminal = os.dup(1), os.dup(2)
    try:
        with path.open("ab") as log, path.open("a", buffering=1, encoding="utf-8") as text:
            os.dup2(log.fileno(), 1)
            os.dup2(log.fileno(), 2)
            try:
                with contextlib.redirect_stdout(text), contextlib.redirect_stderr(text):
                    yield
            finally:
                sys.stdout.flush()
                sys.stderr.flush()
                os.dup2(terminal[0], 1)
                os.dup2(terminal[1], 2)
    finally:
        os.close(terminal[0])
        os.close(terminal[1])


def bootstrap_windows(today: date) -> list[tuple[date, date]]:
    """The two most recent years ending today, then every earlier day of the calendar."""
    split = today - RECENT
    return [(split + timedelta(days=1), today), (INGESTION_DAYS.start.date(), split)]


def refuse_unless_ready(
    connection: psycopg.Connection, instance: DagsterInstance, target: str
) -> None:
    """Refuse a database behind the latest migration, and a flow while another or dbt still runs."""
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

    sessions = [
        pid for (pid,) in connection.execute(DBT_SESSIONS, (f'%"target_name": "{target}"%',))
    ]
    if sessions:
        raise FlowRefused(f"dbt is still building {target}, database sessions {sessions}")


@dataclass
class FlowReport:
    """What one run of a flow did, source by source."""

    first: date
    last: date
    counts: dict[str, dict[str, int]]
    failures: list[tuple[str, str, str]]
    checks_passed: int
    warned_checks: list[tuple[str, int | None]]
    failed_checks: list[tuple[str, int | None]]
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
            read = (
                "not run"
                if counts is None
                else "  ".join(f"{f} {counts.get(f, '-')}" for f in fields)
            )
            shown.append(f"  {source:<22} {read}")
        shown += [f"  failed {source} {key}: {detail}" for source, key, detail in self.failures]
        shown.append(
            f"  checks {self.checks_passed} passed, {len(self.warned_checks)} warned,"
            f" {len(self.failed_checks)} failed"
        )
        shown += [f"  check warned: {found(name, rows)}" for name, rows in self.warned_checks]
        shown += [f"  check failed: {found(name, rows)}" for name, rows in self.failed_checks]
        shown += [f"  step failed: {name}" for name in self.failed_steps]
        shown += [f"  not materialized: {name}" for name in self.unmaterialized]
        return shown


def found(name: str, rows: int | None) -> str:
    return name if rows is None else f"{name}, {rows} rows"


def rows_found(check: AssetCheckEvaluation) -> int | None:
    value = check.metadata.get(ROWS_FOUND)
    return value.value if value is not None and isinstance(value.value, int) else None


def checks_by_outcome(
    checks: Sequence[AssetCheckEvaluation],
) -> tuple[int, list[tuple[str, int | None]], list[tuple[str, int | None]]]:
    """The checks passed, then those not passed at warning severity and at error severity.

    Each check that did not pass carries the rows it found, where the check records them.
    """
    passed = sum(1 for check in checks if check.passed)
    warned = sorted(
        (
            (check.check_name, rows_found(check))
            for check in checks
            if not check.passed and check.severity == AssetCheckSeverity.WARN
        ),
        key=lambda outcome: outcome[0],
    )
    failed = sorted(
        (
            (check.check_name, rows_found(check))
            for check in checks
            if not check.passed and check.severity != AssetCheckSeverity.WARN
        ),
        key=lambda outcome: outcome[0],
    )
    return passed, warned, failed


def run_times(record: RunRecord) -> tuple[datetime, datetime]:
    """A run's start and end, or for a run that never started its creation and last change."""
    started = record.start_time or record.create_timestamp.timestamp()
    ended = record.end_time or max(started, record.update_timestamp.timestamp())
    return datetime.fromtimestamp(started, UTC), datetime.fromtimestamp(ended, UTC)


def report_from(
    record: RunRecord, events: Sequence[EventLogEntry], connection: psycopg.Connection
) -> FlowReport:
    """A finished run's report from its stored events, against the assets that run planned."""
    counts: dict[str, dict[str, int]] = {}
    planned: set[str] = set()
    checks: list[AssetCheckEvaluation] = []
    failed_steps: set[str] = set()
    for event in (entry.dagster_event for entry in events if entry.dagster_event is not None):
        if event.is_step_materialization and event.asset_key is not None:
            metadata = event.step_materialization_data.materialization.metadata
            counts[event.asset_key.to_user_string()] = {
                name: int(value.value)
                for name, value in metadata.items()
                if isinstance(value.value, int)
            }
        elif event.is_asset_materialization_planned and event.asset_key is not None:
            planned.add(event.asset_key.to_user_string())
        elif event.event_type == DagsterEventType.ASSET_CHECK_EVALUATION:
            checks.append(event.asset_check_evaluation_data)
        elif event.is_step_failure and event.step_key is not None:
            failed_steps.add(event.step_key)

    failures = [
        (source, key, detail or "")
        for source, key, detail in connection.execute(FAILED_ATTEMPTS, run_times(record))
    ]
    checks_passed, warned_checks, failed_checks = checks_by_outcome(checks)
    tags = record.dagster_run.tags
    return FlowReport(
        first=date.fromisoformat(tags[RANGE_START]),
        last=date.fromisoformat(tags[RANGE_END]),
        counts=counts,
        failures=failures,
        checks_passed=checks_passed,
        warned_checks=warned_checks,
        failed_checks=failed_checks,
        failed_steps=sorted(failed_steps),
        unmaterialized=sorted(planned - set(counts)),
    )


def steps_of(events: Sequence[EventLogEntry]) -> list[tuple[str, datetime | None, datetime, str]]:
    """Each finished step of a run with its start, end and outcome; a step still going is left out."""
    starts: dict[str, datetime] = {}
    steps = []
    for entry in events:
        event = entry.dagster_event
        if event is None or event.step_key is None:
            continue
        at = datetime.fromtimestamp(entry.timestamp, UTC)
        if event.event_type == DagsterEventType.STEP_START:
            starts[event.step_key] = at
        elif event.event_type in STEP_ENDS:
            ended = STEP_ENDS[event.event_type]
            steps.append((event.step_key, starts.get(event.step_key), at, ended))
    return steps


def outcome_of(status: DagsterRunStatus, report: FlowReport) -> str:
    """The launcher's verdict: Dagster counts a run with a failed day or check a success."""
    if status == DagsterRunStatus.CANCELED:
        return "cancelled"
    return "succeeded" if report.is_clean else "failed"


def writes_here(record: RunRecord, connection: psycopg.Connection, schema: str) -> bool:
    """Whether a run wrote here, by its schema tag or else by a fetch logged here while it ran."""
    written = record.dagster_run.tags.get(SCHEMA_TAG)
    if written is not None:
        return written == schema
    row = connection.execute(FETCHED_DURING, run_times(record)).fetchone()
    return row is not None and bool(row[0])


def record_finished_runs(
    instance: DagsterInstance, connection: psycopg.Connection, schema: str
) -> list[str]:
    """Record each finished flow run this database has not recorded, oldest first."""
    records = instance.get_run_records(
        RunsFilter(tags={FLOW_TAG: [BOOTSTRAP, SYNC]}, statuses=FINISHED)
    )
    run_ids = [record.dagster_run.run_id for record in records]
    known = {run_id for (run_id,) in connection.execute(RECORDED, (run_ids,))}
    recorded = []
    for record in sorted(records, key=lambda record: record.create_timestamp):
        run = record.dagster_run
        if run.run_id in known or not writes_here(record, connection, schema):
            continue
        events = instance.all_logs(run.run_id)
        report = report_from(record, events, connection)
        started, ended = run_times(record)
        connection.execute(
            RECORD_RUN,
            {
                "run_id": run.run_id,
                "flow": run.tags[FLOW_TAG],
                "first_day": report.first,
                "last_day": report.last,
                "started_at": started,
                "ended_at": ended,
                "outcome": outcome_of(run.status, report),
                "counts": Jsonb(report.counts),
                "checks_passed": report.checks_passed,
                "failures": Jsonb(
                    [{"source": s, "key": k, "detail": d} for s, k, d in report.failures]
                ),
                "warned_checks": Jsonb([{"name": n, "rows": r} for n, r in report.warned_checks]),
                "failed_checks": Jsonb([{"name": n, "rows": r} for n, r in report.failed_checks]),
                "failed_steps": Jsonb(report.failed_steps),
                "unmaterialized": Jsonb(report.unmaterialized),
            },
        )
        for step in steps_of(events):
            connection.execute(RECORD_STEP, (run.run_id, *step))
        recorded.append(run.run_id)
    connection.commit()
    return recorded


def run_window(
    instance: DagsterInstance,
    job: Callable[[], JobDefinition],
    first: date,
    last: date,
    schema: str,
) -> FlowReport:
    tags = {RANGE_START: first.isoformat(), RANGE_END: last.isoformat(), SCHEMA_TAG: schema}
    with execute_job(reconstructable(job), instance=instance, tags=tags) as result:
        run_id = result.run_id

    record = instance.get_run_record_by_id(run_id)
    assert record is not None
    with Database().connect() as connection:
        return report_from(record, instance.all_logs(run_id), connection)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipelines.flows")
    parser.add_argument("flow", choices=(BOOTSTRAP, SYNC))
    parser.add_argument("--from", dest="first", type=date.fromisoformat)
    parser.add_argument("--to", dest="last", type=date.fromisoformat)
    parser.add_argument("--day", type=date.fromisoformat, help="a sync's last day, today if unset")
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="print each run's output rather than keep it in a file",
    )
    args = parser.parse_args(argv)
    if (args.first is None) != (args.last is None) or (args.day and args.flow == BOOTSTRAP):
        parser.error("--from and --to go together, and --day belongs to a sync")

    started = datetime.now(VENUE_TIME)
    today = started.date()
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
            refuse_unless_ready(connection, instance, settings.data_env)
    except FlowRefused as refusal:
        print(f"{args.flow} not started: {refusal}", file=sys.stderr)
        return 2

    log = Path(instance.root_directory) / LOG_FOLDER / f"{args.flow}-{started:%Y%m%d-%H%M%S}.log"
    if not args.verbose:
        print(f"run output in {log}")

    def output() -> contextlib.AbstractContextManager[None]:
        return contextlib.nullcontext() if args.verbose else output_to(log)

    reports = []
    for first, last in windows:
        with output():
            report = run_window(instance, job, first, last, settings.schema_name)
        print("\n".join(report.lines()), flush=True)
        reports.append(report)
        with Database().connect() as connection:
            record_finished_runs(instance, connection, settings.schema_name)
    return 0 if all(report.is_clean for report in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
