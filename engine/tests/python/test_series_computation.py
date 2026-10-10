import importlib.metadata
import importlib.resources
import itertools
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

import btcore

NAN = np.nan
CLOSES = np.array([10.0, 12.0, 11.0, 15.0, 14.0])
COMPUTATIONS = [
    btcore.sma,
    btcore.ema,
    btcore.rsi,
    btcore.variance,
    btcore.simple_return,
    btcore.realised_volatility,
    btcore.change,
    btcore.rolling_maximum,
    btcore.rolling_minimum,
    btcore.new_high,
    btcore.new_low,
    btcore.ratio_to_prior_mean,
]

type Computation = Callable[..., np.ndarray]


def walk(length: int, seed: int) -> np.ndarray:
    steps = 1 + 0.02 * np.random.default_rng(seed).standard_normal(length)
    return 100 * np.cumprod(steps)


def test_a_series_is_averaged_over_its_window() -> None:
    np.testing.assert_array_equal(btcore.sma(CLOSES, 3), [NAN, NAN, 11.0, 38 / 3, 40 / 3])
    np.testing.assert_array_equal(btcore.ema(CLOSES, 3), [NAN, NAN, 11.0, 13.0, 13.5])
    np.testing.assert_allclose(btcore.rsi(CLOSES, 2), [NAN, NAN, 200 / 3, 1000 / 11, 200 / 3])
    np.testing.assert_allclose(btcore.variance(CLOSES, 3), [NAN, NAN, 2 / 3, 26 / 9, 26 / 9])
    np.testing.assert_allclose(
        btcore.variance(CLOSES, 3, sample=True), [NAN, NAN, 1.0, 13 / 3, 13 / 3]
    )


def test_rolling_extremes_keep_the_ends_of_each_window() -> None:
    np.testing.assert_array_equal(btcore.rolling_maximum(CLOSES, 2), [NAN, 12, 12, 15, 15])
    np.testing.assert_array_equal(btcore.rolling_minimum(CLOSES, 2), [NAN, 10, 11, 11, 14])


def test_range_positions_measure_against_the_window() -> None:
    np.testing.assert_array_equal(btcore.new_high(CLOSES, 2), [NAN, 1.0, 0.0, 1.0, 0.0])
    np.testing.assert_array_equal(btcore.new_low(CLOSES, 2), [NAN, 0.0, 1.0, 0.0, 1.0])
    distance = btcore.distance_from_high(CLOSES, CLOSES + 1, 2)
    np.testing.assert_allclose(distance, [NAN, -1 / 13, -2 / 13, -1 / 16, -2 / 16])
    highs = CLOSES + 1
    with pytest.raises(ValueError, match="shares memory"):
        btcore.distance_from_high(CLOSES, highs, 2, out=highs)


def test_traded_value_compares_volume_and_delivery() -> None:
    np.testing.assert_allclose(
        btcore.ratio_to_prior_mean(CLOSES, 2), [NAN, NAN, 1.0, 15 / 11.5, 14 / 13]
    )
    delivered = np.array([5.0, NAN, 11.0, 3.0, 7.0])
    np.testing.assert_allclose(btcore.percentage_of(delivered, CLOSES), delivered / CLOSES * 100)
    with pytest.raises(ValueError, match="shares memory"):
        btcore.percentage_of(delivered, CLOSES, out=delivered)


def test_on_balance_volume_follows_the_direction_of_the_close() -> None:
    volumes = np.array([100.0, 50.0, 60.0, 70.0, 20.0])
    np.testing.assert_array_equal(
        btcore.on_balance_volume(CLOSES, volumes), [100, 150, 90, 160, 140]
    )
    offsets = np.array([0, 2, 5], dtype=np.int64)
    np.testing.assert_array_equal(
        btcore.on_balance_volume(CLOSES, volumes, offsets=offsets), [100, 150, 60, 130, 110]
    )


def test_primary_venue_designates_each_day_from_turnover() -> None:
    days = np.array(["2024-03-04", "2024-03-05", "2024-04-01", "2024-05-02"], dtype="datetime64[D]")
    bse = np.array([40.0, NAN, 1.0, 1.0])
    nse = np.array([30.0, 5.0, 50.0, 1.0])
    venues = btcore.primary_venue(days.view(np.int64), bse, nse)
    assert venues.dtype == np.int8
    np.testing.assert_array_equal(venues, [0, 0, 0, 1])
    with pytest.raises(TypeError):
        btcore.primary_venue(days, bse, nse)
    with pytest.raises(ValueError, match="days must rise"):
        btcore.primary_venue(days.view(np.int64)[::-1].copy(), bse, nse)


def test_a_change_subtracts_the_value_bars_before() -> None:
    np.testing.assert_array_equal(btcore.change(CLOSES, 1), [NAN, 2.0, -1.0, 4.0, -1.0])


def test_a_return_measures_from_the_value_bars_before() -> None:
    returns = [NAN, 0.2, -1 / 12, 4 / 11, -1 / 15]
    np.testing.assert_allclose(btcore.simple_return(CLOSES, 1), returns)
    np.testing.assert_allclose(btcore.simple_return(CLOSES, 1, skip=1), [NAN, *returns[:-1]])


def test_volatility_annualises_the_deviation_of_log_returns() -> None:
    log_returns = np.log1p(np.diff(CLOSES) / CLOSES[:-1])
    expected = [log_returns[end - 2 : end].std(ddof=1) * np.sqrt(252) for end in (2, 3, 4)]
    np.testing.assert_allclose(btcore.realised_volatility(CLOSES, 2), [NAN, NAN, *expected])


@pytest.mark.parametrize("computation", COMPUTATIONS)
def test_the_universe_form_matches_each_series_on_any_thread_count(
    computation: Computation,
) -> None:
    values = walk(1_000, seed=7)
    offsets = np.array([0, 300, 300, 750, 1_000], dtype=np.int64)
    each = np.concatenate(
        [computation(values[start:end], 20) for start, end in itertools.pairwise(offsets)]
    )
    for threads in (1, 8):
        result = computation(values, 20, offsets=offsets, threads=threads)
        np.testing.assert_array_equal(result, each)


@pytest.mark.parametrize("computation", COMPUTATIONS)
def test_the_result_is_written_into_out(computation: Computation) -> None:
    out = np.full(CLOSES.size, -1.0)
    assert computation(CLOSES, 3, out=out) is out
    np.testing.assert_array_equal(out, computation(CLOSES, 3))


@pytest.mark.parametrize(
    "arguments",
    [
        {"values": CLOSES.astype(np.float32)},
        {"values": CLOSES.astype(np.int64)},
        {"values": CLOSES[::2]},
        {"values": CLOSES.reshape(1, -1)},
        {"values": CLOSES.tolist()},
        {"offsets": np.array([0, 5], dtype=np.int32)},
        {"out": np.empty(CLOSES.size, dtype=np.float32)},
        {"out": np.empty(CLOSES.size)[::-1]},
        {"out": np.frombuffer(np.empty(CLOSES.size).tobytes())},
    ],
    ids=[
        "float32",
        "integers",
        "strided",
        "two dimensions",
        "list",
        "int32 offsets",
        "float32 out",
        "strided out",
        "read-only out",
    ],
)
def test_an_array_that_needs_converting_is_refused(arguments: dict[str, Any]) -> None:
    call = {"values": CLOSES} | arguments
    with pytest.raises(TypeError):
        btcore.sma(call.pop("values"), 3, **call)


def test_arguments_the_engine_cannot_accept_raise_value_error() -> None:
    with pytest.raises(ValueError, match="period"):
        btcore.sma(CLOSES, 0)
    with pytest.raises(ValueError, match="output holds 4 values"):
        btcore.sma(CLOSES, 3, out=np.empty(CLOSES.size - 1))
    with pytest.raises(ValueError, match="offsets end at 3"):
        btcore.sma(CLOSES, 3, offsets=np.array([0, 3], dtype=np.int64))


def test_an_out_sharing_memory_with_values_is_refused() -> None:
    values = CLOSES.copy()
    with pytest.raises(ValueError, match="shares memory"):
        btcore.sma(values, 3, out=values)
    with pytest.raises(ValueError, match="shares memory"):
        btcore.sma(values[:4], 3, out=values[1:])


def test_bollinger_bands_lie_width_deviations_from_the_average() -> None:
    upper, lower = btcore.bollinger_bands(CLOSES, 3)
    deviation = np.sqrt(btcore.variance(CLOSES, 3))
    np.testing.assert_array_equal(upper, btcore.sma(CLOSES, 3) + 2 * deviation)
    np.testing.assert_array_equal(lower, btcore.sma(CLOSES, 3) - 2 * deviation)


def test_bollinger_bands_fill_out_and_spread_over_threads() -> None:
    out = (np.empty(CLOSES.size), np.empty(CLOSES.size))
    upper, lower = btcore.bollinger_bands(CLOSES, 3, out=out)
    assert upper is out[0] and lower is out[1]
    values = walk(1_000, seed=7)
    offsets = np.array([0, 300, 300, 750, 1_000], dtype=np.int64)
    pieces = [btcore.bollinger_bands(values[a:b], 20) for a, b in itertools.pairwise(offsets)]
    for threads in (1, 8):
        spread = btcore.bollinger_bands(values, 20, offsets=offsets, threads=threads)
        for line in (0, 1):
            np.testing.assert_array_equal(spread[line], np.concatenate([p[line] for p in pieces]))


def test_bollinger_bands_refuse_overlapping_lines_and_a_negative_width() -> None:
    line = np.empty(CLOSES.size)
    with pytest.raises(ValueError, match="shares memory"):
        btcore.bollinger_bands(CLOSES, 3, out=(line, line))
    with pytest.raises(ValueError, match="width"):
        btcore.bollinger_bands(CLOSES, 3, width=-1.0)


def test_the_package_reports_its_version_and_ships_type_stubs() -> None:
    assert btcore.version() == importlib.metadata.version("btcore")
    package = importlib.resources.files("btcore")
    assert (package / "py.typed").is_file()
    assert "def sma(" in (package / "_btcore.pyi").read_text()


def daily_bars(length: int, seed: int) -> dict[str, np.ndarray]:
    """A drawn walk read as every price, its factor halving the scale of the first half."""
    close = walk(length, seed)
    return {
        "close": close,
        "high": close * 1.01,
        "low": close * 0.99,
        "volume": np.full(length, 1_000.0),
        "delivery": np.full(length, 400.0),
        "turnover": close * 1_000.0,
        "adjustment_factor": np.where(np.arange(length) < length // 2, 0.5, 1.0),
    }


def test_daily_features_hold_every_column_with_its_leading_blanks() -> None:
    bars = daily_bars(300, seed=11)
    table = btcore.daily_features(**bars)
    assert table.shape == (len(btcore.FEATURE_COLUMNS), 300)
    column = dict(zip(btcore.FEATURE_COLUMNS, table, strict=True))
    close, factor = bars["close"], bars["adjustment_factor"]
    np.testing.assert_array_equal(column["sma_20"], btcore.sma(close, 20) / factor)
    np.testing.assert_array_equal(column["rsi_14"], btcore.rsi(close, 14))
    np.testing.assert_array_equal(
        column["delivery_pct_1d"], btcore.percentage_of(bars["delivery"], bars["volume"])
    )
    for name, blanks in zip(btcore.FEATURE_COLUMNS, btcore.FEATURE_LEADING_BLANKS, strict=True):
        assert np.isnan(column[name][:blanks]).all(), name
        assert not np.isnan(column[name][blanks:]).any(), name


def test_daily_features_match_each_series_on_any_thread_count() -> None:
    bars = daily_bars(600, seed=13)
    offsets = np.array([0, 250, 250, 600], dtype=np.int64)
    each = np.concatenate(
        [
            btcore.daily_features(**{name: values[start:end] for name, values in bars.items()})
            for start, end in itertools.pairwise(offsets)
        ],
        axis=1,
    )
    for threads in (1, 8):
        result = btcore.daily_features(**bars, offsets=offsets, threads=threads)
        np.testing.assert_array_equal(result, each)


def test_designated_bars_flag_the_bars_of_each_days_primary_venue() -> None:
    bse_days = np.array(["2024-01-02", "2024-01-03", "2024-02-01"], dtype="datetime64[D]")
    nse_days = np.array(["2024-01-02", "2024-02-01", "2024-02-02"], dtype="datetime64[D]")
    days = np.concatenate([bse_days, nse_days]).view(np.int64)
    turnover = np.array([5.0, 10.0, 1.0, 7.0, 9.0, 9.0])
    offsets = np.array([0, 3, 6], dtype=np.int64)
    flags = btcore.designated_bars(days, turnover, offsets)
    assert flags.dtype == np.uint8
    np.testing.assert_array_equal(flags, [0, 1, 1, 1, 0, 0])
    with pytest.raises(ValueError, match="pairs"):
        btcore.designated_bars(days, turnover, np.array([0, 6], dtype=np.int64))
