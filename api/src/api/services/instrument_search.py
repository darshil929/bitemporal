"""Finding an instrument from what a reader types: part of its name, a symbol, a scrip code or an
ISIN."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts

SEARCH_RESULTS = 10

# A match on an ISIN a change of face value replaced counts for the ISIN that took it over.
# Instruments listed now come first, then the closest match: an exact ISIN, symbol or scrip code,
# a name starting with the text, a symbol or ISIN starting with it, a name holding it. The symbol
# shown is the newest of the stretches open now, NSE's before BSE's.
SEARCH = text(
    """
    with matched as (
        select
            instruments.current_isin as isin,
            min(case
                when instruments.isin = upper(:text) or upper(listings.local_symbol) = upper(:text)
                    or listings.scrip_code = :text then 0
                when instruments.display_name ilike :prefix then 1
                when listings.local_symbol ilike :prefix or instruments.isin ilike :prefix then 2
                else 3
            end) as match_rank
        from mart_instruments as instruments
        left join mart_listings as listings on listings.isin = instruments.isin
        where instruments.display_name ilike :anywhere
            or instruments.isin ilike :prefix
            or listings.local_symbol ilike :prefix
            or listings.scrip_code = :text
        group by instruments.current_isin
    ),

    described as (
        select
            current.isin,
            current.display_name,
            matched.match_rank,
            (
                select symbols.local_symbol from mart_listings as symbols
                where symbols.isin = current.isin
                order by symbols.delisting_date is null desc, symbols.exchange = 'NSE' desc,
                    symbols.listing_date desc
                limit 1
            ) as symbol,
            array(
                select distinct venues.exchange from mart_listings as venues
                where venues.isin = current.isin and venues.delisting_date is null
                order by venues.exchange
            ) as venues
        from matched inner join mart_instruments as current on matched.isin = current.isin
    )

    select isin, display_name, symbol, venues from described
    order by cardinality(venues) = 0, match_rank, display_name, isin
    limit :results
    """
)


@dataclass(frozen=True)
class InstrumentMatch:
    isin: str
    display_name: str
    symbol: str | None
    venues: list[str]


def literal_pattern(typed: str) -> str:
    """The typed text with the pattern characters of `ilike` standing for themselves."""
    return typed.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_instruments(database: Database, typed: str) -> tuple[InstrumentMatch, ...]:
    literal = literal_pattern(typed)
    values = {
        "text": typed,
        "prefix": f"{literal}%",
        "anywhere": f"%{literal}%",
        "results": SEARCH_RESULTS,
    }

    async def read(transaction: AsyncSession) -> tuple[InstrumentMatch, ...]:
        return tuple(InstrumentMatch(*row) for row in await transaction.execute(SEARCH, values))

    return await read_marts(database, read)
