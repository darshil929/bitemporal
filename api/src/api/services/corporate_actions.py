"""An instrument's corporate actions, as its actions table and price chart show them."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.key_figures import CURRENT
from api.services.market_reads import read_marts
from api.services.price_history import number

# Actions are kept under the ISIN the instrument trades under now, so a replaced ISIN's list holds
# the change of face value that replaced it.
ACTIONS = text(
    """
    select
        ex_date, action_type, qualifier, terms, adjustment_factor, dividend_amount, purpose,
        reported_by, venues_differ, is_applied, source_id
    from mart_corporate_actions
    where isin = :current and ex_date <= coalesce(cast(:published_day as date), 'infinity')
    order by ex_date desc, action_type asc, qualifier asc
    """
)


@dataclass(frozen=True)
class CorporateAction:
    ex_date: date
    action_type: str
    qualifier: str
    terms: str | None
    adjustment_factor: float | None
    dividend_amount: float | None
    purpose: str | None
    reported_by: str
    venues_differ: bool
    is_applied: bool | None
    source_id: str | None


async def corporate_actions(database: Database, isin: str) -> tuple[CorporateAction, ...] | None:
    """The instrument's actions with an ex-date up to the published day, newest first."""

    async def read(transaction: AsyncSession) -> tuple[CorporateAction, ...] | None:
        found = (await transaction.execute(CURRENT, {"isin": isin})).one_or_none()
        if found is None:
            return None
        scope = {"current": found.current_isin, "published_day": found.published_day}
        return tuple(
            CorporateAction(
                ex_date=row.ex_date,
                action_type=row.action_type,
                qualifier=row.qualifier,
                terms=row.terms,
                adjustment_factor=number(row.adjustment_factor),
                dividend_amount=number(row.dividend_amount),
                purpose=row.purpose,
                reported_by=row.reported_by,
                venues_differ=row.venues_differ,
                is_applied=row.is_applied,
                source_id=row.source_id,
            )
            for row in await transaction.execute(ACTIONS, scope)
        )

    return await read_marts(database, read)
