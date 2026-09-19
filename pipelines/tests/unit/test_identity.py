"""Identity derivation from observed bars."""

from datetime import date
from decimal import Decimal

import pytest

from pipelines.identity import (
    UnresolvedInstrument,
    derive_listings,
    derive_primary_venue,
    derive_successions,
    require_resolvable,
)
from pipelines.models.market import PriceBar

RELIANCE = "INE002A01018"
INFOSYS = "INE009A01021"
SHRIRAM_OLD = "INE721A01013"
SHRIRAM_NEW = "INE721A01047"


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


def test_a_stretch_ended_by_a_change_of_isin_is_superseded() -> None:
    """Shriram Finance kept its scrip code and ticker across the split that issued a new ISIN."""
    bars = [
        bar(
            isin=SHRIRAM_OLD,
            venue="BSE",
            symbol="SHRIRAMFIN",
            scrip_code="511218",
            day="2024-01-02",
        ),
        bar(
            isin=SHRIRAM_OLD,
            venue="BSE",
            symbol="SHRIRAMFIN",
            scrip_code="511218",
            day="2025-01-09",
        ),
        bar(
            isin=SHRIRAM_NEW,
            venue="BSE",
            symbol="SHRIRAMFIN",
            scrip_code="511218",
            day="2025-01-10",
        ),
        bar(
            isin=SHRIRAM_NEW,
            venue="BSE",
            symbol="SHRIRAMFIN",
            scrip_code="511218",
            day="2025-12-01",
        ),
    ]

    listings = derive_listings(bars, {"BSE": date(2025, 12, 1)})

    assert [(item.isin, item.closure_reason) for item in listings] == [
        (SHRIRAM_OLD, "superseded"),
        (SHRIRAM_NEW, None),
    ]
    assert listings[0].delisting_date == date(2025, 1, 9)


def test_the_ticker_carries_the_supersession_at_nse() -> None:
    """NSE publishes no scrip code, so the ticker is what runs through the change."""
    bars = [
        bar(isin=SHRIRAM_OLD, symbol="SHRIRAMFIN", day="2024-01-02"),
        bar(isin=SHRIRAM_OLD, symbol="SHRIRAMFIN", day="2025-01-09"),
        bar(isin=SHRIRAM_NEW, symbol="SHRIRAMFIN", day="2025-01-10"),
        bar(isin=SHRIRAM_NEW, symbol="SHRIRAMFIN", day="2025-12-01"),
    ]

    listings = derive_listings(bars, {"NSE": date(2025, 12, 1)})

    assert [item.closure_reason for item in listings] == ["superseded", None]


def test_a_later_arrival_under_the_same_ticker_is_not_a_supersession() -> None:
    """A ticker reused weeks afterwards is a different instrument, not a successor."""
    bars = [
        bar(isin=SHRIRAM_OLD, symbol="SHRIRAMFIN", day="2024-01-02"),
        bar(isin=SHRIRAM_OLD, symbol="SHRIRAMFIN", day="2025-01-09"),
        bar(isin=SHRIRAM_NEW, symbol="SHRIRAMFIN", day="2025-03-10"),
        bar(isin=SHRIRAM_NEW, symbol="SHRIRAMFIN", day="2025-12-01"),
    ]

    listings = derive_listings(bars, {"NSE": date(2025, 12, 1)})

    assert [item.closure_reason for item in listings] == ["delisted", None]


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


def test_a_superseded_stretch_names_the_isin_that_took_it_over() -> None:
    """The scrip code runs through the change, so it is what links the two ISINs."""
    bars = [
        bar(isin=SHRIRAM_OLD, venue="BSE", symbol="SHRIRAMFIN", scrip_code="511218", day=day)
        for day in ("2024-01-02", "2025-01-09")
    ] + [
        bar(isin=SHRIRAM_NEW, venue="BSE", symbol="SHRIRAMFIN", scrip_code="511218", day=day)
        for day in ("2025-01-10", "2025-12-01")
    ]

    successions = derive_successions(derive_listings(bars, {"BSE": date(2025, 12, 1)}))

    assert len(successions) == 1
    assert successions[0].predecessor_isin == SHRIRAM_OLD
    assert successions[0].successor_isin == SHRIRAM_NEW
    assert successions[0].exchange == "BSE"
    assert successions[0].changed_on == date(2025, 1, 10)


def test_a_ticker_reused_later_leaves_no_succession() -> None:
    """Nothing links the two, so the earlier stretch stays delisted and is not stitched onward."""
    bars = [
        bar(isin=SHRIRAM_OLD, symbol="SHRIRAMFIN", day="2024-01-02"),
        bar(isin=SHRIRAM_OLD, symbol="SHRIRAMFIN", day="2025-01-09"),
        bar(isin=SHRIRAM_NEW, symbol="SHRIRAMFIN", day="2025-03-10"),
        bar(isin=SHRIRAM_NEW, symbol="SHRIRAMFIN", day="2025-12-01"),
    ]

    assert derive_successions(derive_listings(bars, {"NSE": date(2025, 12, 1)})) == ()


def test_a_listing_still_trading_has_no_successor() -> None:
    bars = [bar(day="2025-01-02"), bar(day="2025-12-01")]

    assert derive_successions(derive_listings(bars, {"NSE": date(2025, 12, 1)})) == ()
