"""Reading stored bars back for the derivations that need the whole history rather than a day.

Each query resolves the version history the way `stg_price_daily` does, taking the latest bar at
or before the as-of date, and returns a summary rather than the bars themselves: a listing stretch
covers years of rows, and the full universe holds tens of millions.
"""

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from pipelines.identity import Stretch

logger = logging.getLogger(__name__)

# A venue names an instrument the same way for years at a time, so the days it did are collapsed
# into stretches in SQL. `changed` opens a stretch, and the running sum numbers them.
STRETCHES = """
with resolved as (
    select distinct on (isin, venue, trade_date)
        isin, venue, trade_date, local_symbol, scrip_code
    from price_daily
    where as_of_date <= %(as_of)s
    order by isin, venue, trade_date, as_of_date desc
),
marked as (
    select *,
        case
            when lag(local_symbol) over line is distinct from local_symbol then 1
            else 0
        end as changed
    from resolved
    window line as (partition by isin, venue, coalesce(scrip_code, '') order by trade_date)
),
numbered as (
    select *,
        sum(changed) over (
            partition by isin, venue, coalesce(scrip_code, '') order by trade_date
        ) as stretch
    from marked
)
select isin, venue, local_symbol, max(scrip_code) as scrip_code,
       min(trade_date) as first_day, max(trade_date) as last_day
from numbered
group by isin, venue, coalesce(scrip_code, ''), stretch, local_symbol
order by isin, venue, min(trade_date)
"""

TURNOVER = """
select distinct on (isin, venue, trade_date) isin, venue, trade_date, turnover
from price_daily
where as_of_date <= %(as_of)s
order by isin, venue, trade_date, as_of_date desc
"""

VENUE_LAST_DAYS = """
select venue, max(trade_date) from price_daily where as_of_date <= %(as_of)s group by venue
"""

FAR_FUTURE = date(9999, 12, 31)


@dataclass(frozen=True)
class TurnoverPoint:
    """What one instrument traded at one venue on one day, which designates a primary venue."""

    isin: str
    venue: str
    trade_date: date
    turnover: Decimal | None


def read_stretches(connection: psycopg.Connection, as_of: date = FAR_FUTURE) -> tuple[Stretch, ...]:
    rows = connection.execute(STRETCHES, {"as_of": as_of}).fetchall()
    stretches = tuple(Stretch(*row) for row in rows)

    logger.info("stretches read", extra={"stretches": len(stretches)})
    return stretches


def read_turnover(
    connection: psycopg.Connection, as_of: date = FAR_FUTURE
) -> tuple[TurnoverPoint, ...]:
    rows = connection.execute(TURNOVER, {"as_of": as_of}).fetchall()
    return tuple(TurnoverPoint(*row) for row in rows)


def venue_last_days(connection: psycopg.Connection, as_of: date = FAR_FUTURE) -> dict[str, date]:
    return {venue: last for venue, last in connection.execute(VENUE_LAST_DAYS, {"as_of": as_of})}
