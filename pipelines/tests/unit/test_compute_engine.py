"""The compute engine as the pipelines call it."""

import numpy as np

import btcore


def test_the_engine_computes_over_numpy_arrays() -> None:
    averages = btcore.sma(np.array([10.0, 12.0, 11.0]), 2)

    np.testing.assert_array_equal(averages, [np.nan, 11.0, 11.5])
