"""Bodies of the saved screener view reads and changes."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

ViewName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
ViewQuery = Annotated[str, StringConstraints(max_length=2000)]


class SavedViewRequest(BaseModel):
    """A screen to keep under a name: the screener's address after its `?`."""

    name: ViewName
    query: ViewQuery


class SavedViewChangeRequest(BaseModel):
    """A new name for a view, a screen to save over it, or both."""

    name: ViewName | None = None
    query: ViewQuery | None = None


class SavedViewResponse(BaseModel):
    """A view the person keeps: its screen's parts in a fixed order, without a page."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    query: str
    created_at: datetime
    updated_at: datetime


class ViewRefused(BaseModel):
    reason: Literal["view_name_taken", "view_not_found"]


class ViewRefusedResponse(BaseModel):
    detail: ViewRefused
