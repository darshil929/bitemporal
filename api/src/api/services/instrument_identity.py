"""What the application knows an instrument by: its names, where it is listed, and the venue its
pages open on."""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.db.database import Database
from api.services.market_reads import read_marts

INSTRUMENT = text(
    "select instruments.name, instruments.display_name, instruments.instrument_type,"
    " instruments.current_isin, primary_venues.primary_venue"
    " from mart_instruments as instruments"
    " left join mart_primary_venue as primary_venues on primary_venues.isin = instruments.isin"
    " where instruments.isin = :isin"
)
LISTINGS = text(
    "select exchange, local_symbol, scrip_code, listing_date, delisting_date, closure_reason"
    " from mart_listings where isin = :isin order by exchange, listing_date"
)


@dataclass(frozen=True)
class Listing:
    """A stretch during which the instrument traded under one symbol at one venue."""

    exchange: str
    local_symbol: str
    scrip_code: str | None
    listing_date: date
    delisting_date: date | None
    closure_reason: str | None


@dataclass(frozen=True)
class Instrument:
    """An instrument, the ISIN that took it over where a change of face value replaced it, the venue
    its newest daily features were computed on, and the venues it is listed at now."""

    isin: str
    name: str
    display_name: str
    instrument_type: str
    superseded_by: str | None
    primary_venue: str | None
    listings: tuple[Listing, ...]

    @property
    def venues(self) -> list[str]:
        return sorted({listing.exchange for listing in self.listings if not listing.delisting_date})

    @property
    def is_single_listed(self) -> bool:
        return len(self.venues) == 1


async def instrument(database: Database, isin: str) -> Instrument | None:
    async def read(transaction: AsyncSession) -> Instrument | None:
        found = (await transaction.execute(INSTRUMENT, {"isin": isin})).one_or_none()
        if found is None:
            return None
        listings = await transaction.execute(LISTINGS, {"isin": isin})
        return Instrument(
            isin=isin,
            name=found.name,
            display_name=found.display_name,
            instrument_type=found.instrument_type,
            superseded_by=found.current_isin if found.current_isin != isin else None,
            primary_venue=found.primary_venue,
            listings=tuple(Listing(*listing) for listing in listings),
        )

    return await read_marts(database, read)
