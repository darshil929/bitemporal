"""Canonical corporate actions."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class CorporateActionRecord(BaseModel):
    """An action that changes the share count or pays out value, as reported on a given date.

    `ratio_from` and `ratio_to` are the share count before and after: a one-for-one bonus is 1 to
    2, a split from a face value of ten to two is 1 to 5. Both collapse to the same adjustment
    factor, so adjustment never branches on action type.
    """

    isin: str
    action_type: str
    ex_date: date
    source_id: str
    as_of_date: date
    qualifier: str = "ordinary"
    ratio_from: Decimal | None = None
    ratio_to: Decimal | None = None
    dividend_amount: Decimal | None = None
