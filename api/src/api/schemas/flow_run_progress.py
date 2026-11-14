"""Bodies of the run progress read."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from api.schemas.flow_run_estimates import DurationResponse

StageName = Literal[
    "prices", "identity", "delivery", "actions", "names", "models", "features", "checks"
]


class StageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: StageName
    state: Literal["done", "running", "pending", "failed"]


class ProgressResponse(BaseModel):
    """A request's run as it stands: its status, each stage in order, the stage running now, and
    the time left by the steps' medians over the last three runs; no time left once the run ended
    or before any run of the flow was measured."""

    model_config = ConfigDict(from_attributes=True)

    status: Literal[
        "requested", "running", "cancelling", "cancelled", "refused", "succeeded", "failed"
    ]
    stages: list[StageResponse]
    current_stage: StageName | None
    time_left: DurationResponse | None
