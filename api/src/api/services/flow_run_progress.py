"""How a requested run stands while it goes: its status, the state of each stage, and the time
left by the steps' medians over the last three runs of the flow."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.flow_run_estimates import MEASURED_RUNS, Duration

STAGES = ("prices", "identity", "delivery", "actions", "names", "models", "features", "checks")
STEP_STAGES = {
    "source_registry": "prices",
    "bse_bhavcopy": "prices",
    "nse_bhavcopy": "prices",
    "instrument_identity": "identity",
    "trading_day_completeness": "identity",
    "bse_delivery": "delivery",
    "nse_delivery": "delivery",
    "corporate_actions": "actions",
    "nse_corporate_actions": "actions",
    "bse_instrument_names": "names",
    "nse_instrument_names": "names",
    "dbt_models": "models",
    "watchlist_alert_evaluation": "features",
}

REQUEST = text(
    "select flow, status, cancel_requested_at is not null as is_cancelling, run_id"
    " from flow_request where id = :id"
)
OUTCOMES = text("select run_id, outcome from flow_run where request_id = :id order by started_at")
# Steps are recorded as they finish, a step skipped included.
STEPS = text("select step, outcome from flow_run_step where run_id = :run")
# The steps a run of the flow takes, as the newest run of it with steps took them.
PLAN = text(
    "select step from flow_run_step where run_id = ("
    " select run_id from flow_run where flow = :flow"
    " and exists (select from flow_run_step where flow_run_step.run_id = flow_run.run_id)"
    " order by started_at desc limit 1)"
)
STEP_MEDIANS = text(
    "with recent as ("
    " select run_id from flow_run where flow = :flow and outcome <> 'cancelled'"
    " and exists (select from flow_run_step where flow_run_step.run_id = flow_run.run_id)"
    " order by started_at desc limit :runs)"
    " select step, percentile_cont(0.5) within group"
    " (order by extract(epoch from ended_at - started_at)) as seconds"
    " from flow_run_step join recent using (run_id) where started_at is not null group by step"
)


@dataclass(frozen=True)
class Stage:
    stage: str
    state: str


@dataclass(frozen=True)
class Progress:
    """`state` of a stage is done, running, pending or failed; the time left is absent once the run
    ended or before any run of the flow was measured."""

    status: str
    stages: tuple[Stage, ...]
    current_stage: str | None
    time_left: Duration | None


def stage_of(step: str) -> str:
    if step in STEP_STAGES:
        return STEP_STAGES[step]
    # The tables the models read are steps of their own, held until every writer finished.
    if step.startswith("market__"):
        return "models"
    return "features" if step.startswith("daily_feature") else "checks"


def status_of(request_status: str, is_cancelling: bool, outcomes: list[str]) -> str:
    """requested, running, cancelling, cancelled, refused, succeeded or failed."""
    if request_status in ("requested", "started"):
        if is_cancelling:
            return "cancelling"
        return "running" if request_status == "started" else "requested"
    if request_status == "finished":
        if "cancelled" in outcomes:
            return "cancelled"
        return "failed" if "failed" in outcomes else "succeeded"
    return request_status


def stages_of(
    planned: set[str], finished: dict[str, str], is_running: bool
) -> tuple[tuple[Stage, ...], str | None]:
    """Each stage of the plan or the run in order, and the stage running now."""
    steps_by_stage: dict[str, set[str]] = {}
    for step in planned | set(finished):
        steps_by_stage.setdefault(stage_of(step), set()).add(step)
    stages, current = [], None
    for name in STAGES:
        steps = steps_by_stage.get(name)
        if not steps:
            continue
        if any(finished.get(step) == "failed" for step in steps):
            state = "failed"
        elif steps <= set(finished):
            state = "done"
        elif is_running and current is None:
            state, current = "running", name
        else:
            state = "pending"
        stages.append(Stage(name, state))
    return tuple(stages), current


async def resolve_progress(transaction: AsyncSession, request_id: int) -> Progress | None:
    request = (await transaction.execute(REQUEST, {"id": request_id})).one_or_none()
    if request is None:
        return None
    runs = (await transaction.execute(OUTCOMES, {"id": request_id})).all()
    status = status_of(request.status, request.is_cancelling, [run.outcome for run in runs])
    # A run still going has no record yet; one that ended is read from its record.
    newest = runs[-1].run_id if runs else None
    run_id = request.run_id if request.status == "started" else newest or request.run_id
    finished = {
        step: outcome for step, outcome in await transaction.execute(STEPS, {"run": run_id})
    }
    planned = {step for (step,) in await transaction.execute(PLAN, {"flow": request.flow})}
    is_running = status in ("running", "cancelling") and request.status == "started"
    stages, current = stages_of(planned, finished, is_running)
    time_left = None
    if is_running:
        medians = {
            row.step: float(row.seconds)
            for row in await transaction.execute(
                STEP_MEDIANS, {"flow": request.flow, "runs": MEASURED_RUNS}
            )
        }
        if medians:
            remaining = sum(medians.get(step, 0.0) for step in planned - set(finished))
            time_left = Duration(round(remaining))
    return Progress(status, stages, current, time_left)


async def run_progress(database: Database, admin_id: int, request_id: int) -> Progress | None:
    async with database.transaction(admin_id) as transaction:
        return await resolve_progress(transaction, request_id)
