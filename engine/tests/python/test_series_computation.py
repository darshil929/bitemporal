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
