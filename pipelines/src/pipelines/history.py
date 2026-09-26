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
from pipelines.models.market import PriceBar

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

BAR_FIELDS = (
    "isin",
    "venue",
    "trade_date",
    "as_of_date",
    "local_symbol",
    "scrip_code",
    "open",
    "high",
    "low",
    "close",
    "previous_close",
    "volume",
    "turnover",
    "trade_count",
)


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


BARS_FOR_DAY = """
select distinct on (isin, venue)
    isin, venue, trade_date, as_of_date, local_symbol, scrip_code,
    open, high, low, close, previous_close, volume, turnover, trade_count
from price_daily
where trade_date = %(trade_date)s and as_of_date <= %(as_of)s
order by isin, venue, as_of_date desc
"""

# A day with no verdict has not been validated, and one validated before a correction arrived is
# revalidated because the correction carries a later as-of date than the verdict standing.
DAYS_AWAITING_A_VERDICT = """
select distinct p.trade_date
from price_daily p
where p.as_of_date <= %(as_of)s
  and not exists (
      select 1 from trading_day d
      where d.venue = p.venue
        and d.trade_date = p.trade_date
        and d.as_of_date >= p.as_of_date
  )
order by p.trade_date
"""

# A day whose bars no longer number what its latest verdict was drawn from. Bars read into the
# history after a verdict carry the day they describe as their as-of date, so their number is what
# shows the day has changed.
DAYS_WHOSE_BARS_CHANGED = """
select held.trade_date
from (
    select venue, trade_date, count(distinct isin) as bars
    from price_daily
    where as_of_date <= %(as_of)s
    group by venue, trade_date
) as held
inner join (
    select distinct on (venue, trade_date) venue, trade_date, bars
    from trading_day
    order by venue, trade_date, as_of_date desc
) as judged
    on judged.venue = held.venue and judged.trade_date = held.trade_date
where judged.bars <> held.bars
group by held.trade_date
order by held.trade_date
"""

# How many instruments a venue usually lists, against which a truncated file is recognised.
TYPICAL_BARS = """
select venue, percentile_disc(0.5) within group (order by bars) as typical
from (
    select venue, trade_date, count(*) as bars
    from price_daily where as_of_date <= %(as_of)s group by venue, trade_date
) as days
group by venue
"""


def read_bars(
    connection: psycopg.Connection, trade_date: date, as_of: date = FAR_FUTURE
) -> tuple[PriceBar, ...]:
    """Every venue's bars for one day, each resolved to the version standing on the as-of date."""
    rows = connection.execute(BARS_FOR_DAY, {"trade_date": trade_date, "as_of": as_of}).fetchall()
    return tuple(PriceBar(**dict(zip(BAR_FIELDS, row, strict=True))) for row in rows)


def days_awaiting_a_verdict(
    connection: psycopg.Connection, as_of: date = FAR_FUTURE
) -> tuple[date, ...]:
    return tuple(row[0] for row in connection.execute(DAYS_AWAITING_A_VERDICT, {"as_of": as_of}))


def days_whose_bars_changed(
    connection: psycopg.Connection, as_of: date = FAR_FUTURE
) -> tuple[date, ...]:
    return tuple(row[0] for row in connection.execute(DAYS_WHOSE_BARS_CHANGED, {"as_of": as_of}))


def typical_bars(connection: psycopg.Connection, as_of: date = FAR_FUTURE) -> dict[str, int]:
    return {
        venue: int(count) for venue, count in connection.execute(TYPICAL_BARS, {"as_of": as_of})
    }
