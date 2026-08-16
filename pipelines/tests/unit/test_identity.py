"""Identity derivation from observed bars."""

from datetime import date
from decimal import Decimal

import pytest

from pipelines.identity import (
    UnresolvedInstrument,
    derive_listings,
    derive_primary_venue,
    require_resolvable,
)
from pipelines.models.market import PriceBar

RELIANCE = "INE002A01018"
INFOSYS = "INE009A01021"


def bar(
    isin: str = RELIANCE,
    venue: str = "NSE",
    day: str = "2025-01-02",
    symbol: str = "RELIANCE",
    scrip_code: str | None = None,
    turnover: str = "1000",
) -> PriceBar:
    return PriceBar(
        isin=isin,
        venue=venue,
        trade_date=date.fromisoformat(day),
        as_of_date=date.fromisoformat(day),
        local_symbol=symbol,
        scrip_code=scrip_code,
        open=Decimal(100),
        high=Decimal(110),
        low=Decimal(95),
        close=Decimal(105),
        previous_close=Decimal(104),
        volume=10,
        turnover=Decimal(turnover),
        trade_count=5,
    )


def test_an_identifier_that_is_not_an_isin_stops_the_ingestion() -> None:
    """Dropping the row instead would quietly shrink the universe."""
    with pytest.raises(UnresolvedInstrument) as failure:
        require_resolvable([bar(), bar(isin="RELIANCE")])

    assert "RELIANCE" in str(failure.value)


def test_resolvable_bars_pass_through_unchanged() -> None:
    bars = [bar(), bar(isin=INFOSYS, symbol="INFY")]

    assert require_resolvable(bars) == tuple(bars)


def test_a_symbol_change_opens_a_second_listing() -> None:
    bars = [
        bar(day="2025-01-02", symbol="ALIVUS"),
        bar(day="2025-06-02", symbol="ALIVUS"),
        bar(day="2025-06-03", symbol="GLS"),
        bar(day="2025-12-01", symbol="GLS"),
    ]

    listings = derive_listings(bars, {"NSE": date(2025, 12, 1)})

    assert [(item.local_symbol, item.closure_reason) for item in listings] == [
        ("ALIVUS", "renamed"),
        ("GLS", None),
    ]
    assert listings[0].delisting_date == date(2025, 6, 2)
    assert listings[1].listing_date == date(2025, 6, 3)


def test_a_listing_that_stops_early_is_recorded_as_delisted() -> None:
    bars = [bar(day="2025-01-02"), bar(day="2025-02-03")]

    listings = derive_listings(bars, {"NSE": date(2025, 12, 1)})

    assert listings[0].closure_reason == "delisted"
    assert listings[0].delisting_date == date(2025, 2, 3)


def test_a_listing_still_trading_at_the_end_stays_open() -> None:
    bars = [bar(day="2025-11-28"), bar(day="2025-12-01")]

    listings = derive_listings(bars, {"NSE": date(2025, 12, 1)})

    assert listings[0].delisting_date is None
    assert listings[0].closure_reason is None


def test_two_security_lines_at_one_venue_stay_separate() -> None:
    """BSE lists an instrument on its T+0 segment beside the ordinary one."""
    bars = [
        bar(venue="BSE", symbol="RELIANCE", scrip_code="500325", day="2025-11-28"),
        bar(venue="BSE", symbol="RELIANCE#", scrip_code="100325", day="2025-11-28"),
    ]

    listings = derive_listings(bars, {"BSE": date(2025, 11, 28)})

    assert {item.scrip_code for item in listings} == {"500325", "100325"}
    assert all(item.closure_reason is None for item in listings)


def test_the_busier_venue_is_designated_primary() -> None:
    bars = [bar(venue="NSE", day=f"2025-01-{day:02d}", turnover="900") for day in range(2, 28)] + [
        bar(venue="BSE", day=f"2025-01-{day:02d}", turnover="100") for day in range(2, 28)
    ]

    designations = derive_primary_venue(bars)

    assert designations
    assert {item.venue for item in designations} == {"NSE"}


def test_a_designation_records_the_date_it_was_computed() -> None:
    """A backtest reads the venue trailing turnover pointed at then, not the one it points at now."""
    bars = [bar(day=f"2025-01-{day:02d}") for day in range(2, 28)]

    designations = derive_primary_venue(bars)

    assert all(item.as_of_date == item.effective_from for item in designations)


def test_a_venue_that_takes_over_opens_a_new_span() -> None:
    early = [bar(venue="BSE", day=f"2025-01-{day:02d}", turnover="900") for day in range(2, 28)]
    early += [bar(venue="NSE", day=f"2025-01-{day:02d}", turnover="100") for day in range(2, 28)]
    late = [bar(venue="NSE", day=f"2025-06-{day:02d}", turnover="900") for day in range(2, 28)]
    late += [bar(venue="BSE", day=f"2025-06-{day:02d}", turnover="100") for day in range(2, 28)]

    designations = derive_primary_venue(early + late)
    venues = [item.venue for item in designations]

    assert venues[0] == "BSE"
    assert "NSE" in venues
    assert designations[0].effective_to is not None, "the earlier span has to close"


def test_the_final_span_stays_open() -> None:
    bars = [bar(day=f"2025-01-{day:02d}") for day in range(2, 28)]

    designations = derive_primary_venue(bars)

    assert designations[-1].effective_to is None
