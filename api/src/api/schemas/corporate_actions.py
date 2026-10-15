"""Bodies of the corporate action reads."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

ActionType = Literal["split", "bonus", "consolidation", "rights", "dividend", "unhandled"]
ReportedBy = Literal["BSE", "NSE", "both", "prices"]


class CorporateActionResponse(BaseModel):
    """An action with its terms as an announcement states them, the factor it applies to earlier
    prices or the dividend in rupees a share, the venue's own text where its terms are unknown, who
    reported it, whether the two venues' records differ, whether its factor is applied, and the
    source of the record shown, absent for a fund's unit split read from the prices."""

    model_config = ConfigDict(from_attributes=True)

    ex_date: date
    action_type: ActionType
    qualifier: str
    terms: str | None
    adjustment_factor: float | None
    dividend_amount: float | None
    purpose: str | None
    reported_by: ReportedBy
    venues_differ: bool
    is_applied: bool | None
    source_id: str | None
