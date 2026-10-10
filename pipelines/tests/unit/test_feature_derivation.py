"""Daily feature rows derived from both venues' series."""

from dataclasses import dataclass, field

import numpy as np
import pytest

import btcore
from pipelines.daily_features import ENGINE_COLUMNS, DailyFeatureRows
from pipelines.feature_derivation import DerivationRefused, derive_daily_features
from pipelines.feature_inputs import ActionDates, ContinuousSeries, Verdicts

HDFC_BANK = "INE040A01034"
RELIANCE = "INE002A01018"
FIRST_DAY = np.datetime64("2025-10-01", "D").astype(np.int64)
RETURN_1D = ENGINE_COLUMNS.index("return_1d")


@dataclass
class Bar:
    isin: str
    venue: str
    day: int
    close: float | None = 100.0
    turnover: float = 1e7
    known: int | None = None
    source_isin: str | None = None


@dataclass
class Inputs:
    bars: list[Bar]
    actions: list[tuple[str, int, int]] = field(default_factory=list)
    missing_verdicts: set[tuple[str, int]] = field(default_factory=set)

    def series(self) -> ContinuousSeries:
        bars = sorted(self.bars, key=lambda bar: (bar.isin, bar.venue, bar.day))
        close = np.array([np.nan if bar.close is None else bar.close for bar in bars])
        return ContinuousSeries(
            isin=np.array([bar.isin for bar in bars], dtype="S12"),
            source_isin=np.array([bar.source_isin or bar.isin for bar in bars], dtype="S12"),
            is_nse=np.array([bar.venue == "NSE" for bar in bars]),
            day=FIRST_DAY + np.array([bar.day for bar in bars], dtype=np.int64),
            as_of_day=FIRST_DAY
            + np.array([bar.day if bar.known is None else bar.known for bar in bars]),
            close=close,
            high=close,
            low=close,
            volume=np.full(len(bars), 1000.0),
            delivery=np.full(len(bars), np.nan),
            turnover=np.array([bar.turnover for bar in bars]),
            adjustment_factor=np.ones(len(bars)),
            close_as_traded=close,
        )

    def action_dates(self) -> ActionDates:
        actions = sorted(self.actions)
        return ActionDates(
            isin=np.array([isin for isin, _, _ in actions], dtype="S12"),
            ex_day=FIRST_DAY + np.array([ex for _, ex, _ in actions], dtype=np.int64),
            as_of_day=FIRST_DAY + np.array([known for _, _, known in actions], dtype=np.int64),
        )

    def verdicts(self) -> Verdicts:
        days = sorted(
            {(bar.venue, bar.day) for bar in self.bars} - self.missing_verdicts,
        )
        return Verdicts(
            is_nse=np.array([venue == "NSE" for venue, _ in days]),
            day=FIRST_DAY + np.array([day for _, day in days], dtype=np.int64),
            is_complete=np.ones(len(days), dtype=bool),
            as_of_day=FIRST_DAY + np.array([day for _, day in days], dtype=np.int64),
        )

    def rows(self, instruments_per_batch: int = 500) -> list[DailyFeatureRows]:
        return list(
            derive_daily_features(
                self.series(), self.action_dates(), self.verdicts(), instruments_per_batch
            )
        )


def dual_listed(isin: str = HDFC_BANK, days: int = 30) -> list[Bar]:
    """NSE carrying ten times BSE's turnover, so NSE is designated throughout."""
    return [
        Bar(
            isin,
            venue,
            day,
            close=100.0 + day + (0.5 if venue == "BSE" else 0.0),
            turnover=turnover,
        )
        for day in range(days)
        for venue, turnover in (("BSE", 1e6), ("NSE", 1e7))
    ]


def only(rows: list[DailyFeatureRows]) -> DailyFeatureRows:
    assert len(rows) == 1
    return rows[0]


def test_a_row_takes_the_values_of_the_venue_designated_that_day() -> None:
    rows = only(Inputs(dual_listed()).rows())
    nse_closes = 100.0 + np.arange(30.0)
    expected = btcore.daily_features(
        nse_closes,
        nse_closes,
        nse_closes,
        np.full(30, 1000.0),
        np.full(30, np.nan),
        np.full(30, 1e7),
        np.ones(30),
    )

    assert rows.primary_venue == ["NSE"] * 30
    np.testing.assert_array_equal(rows.figures, expected)
    assert rows.close[-1] == 129.0


def test_a_day_the_designated_venue_did_not_trade_has_no_row() -> None:
    bars = [bar for bar in dual_listed() if not (bar.venue == "NSE" and bar.day == 12)]

    rows = only(Inputs(bars).rows())

    assert len(rows.isin) == 29
    assert FIRST_DAY + 12 not in rows.trade_date.astype(np.int64)


def test_a_designated_bar_without_a_close_has_no_row() -> None:
    bars = dual_listed()
    next(bar for bar in bars if bar.venue == "NSE" and bar.day == 12).close = None

    rows = only(Inputs(bars).rows())

    assert len(rows.isin) == 29


def test_a_row_is_dated_by_the_latest_input_on_or_before_its_day() -> None:
    bars = dual_listed(days=10)
    next(bar for bar in bars if bar.venue == "BSE" and bar.day == 3).known = 6
    inputs = Inputs(bars, actions=[(HDFC_BANK, 5, 8), (HDFC_BANK, 7, 40)])

    known = only(inputs.rows()).as_of_date.astype(np.int64) - FIRST_DAY

    assert known.tolist() == [0, 1, 2, 6, 6, 8, 8, 40, 40, 40]


def test_a_designated_bar_on_a_day_without_a_verdict_is_refused() -> None:
    inputs = Inputs(dual_listed(), missing_verdicts={("NSE", 4)})

    with pytest.raises(DerivationRefused):
        inputs.rows()


def test_batches_of_instruments_hold_the_same_rows() -> None:
    inputs = Inputs(dual_listed(HDFC_BANK) + dual_listed(RELIANCE))

    whole = only(inputs.rows())
    batches = inputs.rows(instruments_per_batch=1)

    assert len(batches) == 2
    assert [isin for batch in batches for isin in batch.isin] == whole.isin
    np.testing.assert_array_equal(
        np.concatenate([batch.figures for batch in batches], axis=1), whole.figures
    )
    assert whole.figures[RETURN_1D, 1] == pytest.approx(1 / 100)
