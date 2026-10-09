#include <gtest/gtest.h>

#include <algorithm>
#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <cmath>
#include <limits>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::testing::expect_batch_equals_streaming;
using btcore::testing::kPropertyPeriods;
using btcore::testing::SeriesCase;

constexpr auto kWindowBlanks = [](int period) { return period - 1; };

TEST(MovingAverageProperties, SmaBatchEqualsStreaming) {
  expect_batch_equals_streaming<btcore::SmaState>(
      [](std::span<const double> v, int p, std::span<double> o) { btcore::sma(v, p, o); },
      kWindowBlanks);
}

TEST(MovingAverageProperties, EmaBatchEqualsStreaming) {
  expect_batch_equals_streaming<btcore::EmaState>(
      [](std::span<const double> v, int p, std::span<double> o) { btcore::ema(v, p, o); },
      kWindowBlanks);
}

TEST(MovingAverageProperties, AFlatSeriesAveragesToItsLevel) {
  for (const int period : kPropertyPeriods) {
    for (const double level : {0.5, 3.7, 1'234.55, 99'999.95}) {
      const std::vector<double> flat(60, level);
      std::vector<double> out(flat.size());
      btcore::sma(flat, period, out);
      for (std::size_t index = static_cast<std::size_t>(period) - 1; index < out.size(); ++index) {
        ASSERT_DOUBLE_EQ(out[index], level) << "sma " << period << " at " << index;
      }
      btcore::ema(flat, period, out);
      for (std::size_t index = static_cast<std::size_t>(period) - 1; index < out.size(); ++index) {
        ASSERT_DOUBLE_EQ(out[index], level) << "ema " << period << " at " << index;
      }
    }
  }
}

// Each average weighs only values already seen, so it never leaves the range they span.
TEST(MovingAverageProperties, AnAverageStaysWithinTheRangeOfItsInputs) {
  const auto seed = btcore::testing::property_seed();
  for (const SeriesCase& series : btcore::testing::window_cases(20, seed)) {
    SCOPED_TRACE("seed " + std::to_string(seed) + ", " + series.label);
    std::vector<double> simple(series.values.size());
    std::vector<double> exponential(series.values.size());
    btcore::sma(series.values, 20, simple);
    btcore::ema(series.values, 20, exponential);
    double low = std::numeric_limits<double>::infinity();
    double high = -low;
    for (std::size_t index = 0; index < series.values.size(); ++index) {
      if (std::isnan(series.values[index])) {
        low = std::numeric_limits<double>::infinity();
        high = -low;
        continue;
      }
      low = std::min(low, series.values[index]);
      high = std::max(high, series.values[index]);
      for (const double average : {simple[index], exponential[index]}) {
        if (!std::isnan(average)) {
          ASSERT_GE(average, low * (1 - 1e-15)) << "index " << index;
          ASSERT_LE(average, high * (1 + 1e-15)) << "index " << index;
        }
      }
    }
  }
}

TEST(MovingAverageProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) { btcore::sma(batch, 20, out, threads); },
      [](auto values, auto out) { btcore::sma(values, 20, out); });
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) { btcore::ema(batch, 20, out, threads); },
      [](auto values, auto out) { btcore::ema(values, 20, out); });
}

}  // namespace
