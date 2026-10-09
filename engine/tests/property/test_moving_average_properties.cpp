#include <gtest/gtest.h>

#include <algorithm>
#include <bit>
#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <cmath>
#include <cstdint>
#include <limits>
#include <span>
#include <string>
#include <vector>

#include "series_generators.hpp"

namespace {

using btcore::testing::SeriesCase;

constexpr int kPeriods[] = {1, 2, 14, 20};

template <typename State>
std::vector<double> streamed(const std::vector<double>& values, int period) {
  State state(period);
  std::vector<double> out;
  out.reserve(values.size());
  for (const double value : values) {
    out.push_back(state.update(value));
  }
  return out;
}

// Equal bit for bit, a missing value equal to a missing value.
void expect_identical(const std::vector<double>& actual, const std::vector<double>& expected) {
  ASSERT_EQ(actual.size(), expected.size());
  for (std::size_t index = 0; index < expected.size(); ++index) {
    ASSERT_EQ(std::bit_cast<std::uint64_t>(actual[index]),
              std::bit_cast<std::uint64_t>(expected[index]))
        << "index " << index << ": " << actual[index] << " against " << expected[index];
  }
}

template <typename State, typename Batch>
void expect_batch_equals_streaming(Batch batch) {
  const auto seed = btcore::testing::property_seed();
  for (const int period : kPeriods) {
    for (const SeriesCase& series : btcore::testing::window_cases(period, seed)) {
      SCOPED_TRACE("seed " + std::to_string(seed) + ", period " + std::to_string(period) + ", " +
                   series.label);
      std::vector<double> out(series.values.size());
      batch(series.values, period, out);
      expect_identical(out, streamed<State>(series.values, period));
      const auto blanks = static_cast<std::size_t>(
          std::min<std::ptrdiff_t>(period - 1, static_cast<std::ptrdiff_t>(out.size())));
      EXPECT_TRUE(std::all_of(out.begin(), out.begin() + static_cast<std::ptrdiff_t>(blanks),
                              [](double value) { return std::isnan(value); }));
    }
  }
}

TEST(MovingAverageProperties, SmaBatchEqualsStreaming) {
  expect_batch_equals_streaming<btcore::SmaState>(
      [](std::span<const double> v, int p, std::span<double> o) { btcore::sma(v, p, o); });
}

TEST(MovingAverageProperties, EmaBatchEqualsStreaming) {
  expect_batch_equals_streaming<btcore::EmaState>(
      [](std::span<const double> v, int p, std::span<double> o) { btcore::ema(v, p, o); });
}

TEST(MovingAverageProperties, AFlatSeriesAveragesToItsLevel) {
  for (const int period : kPeriods) {
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
  const auto universe = btcore::testing::universe(300, 120, btcore::testing::property_seed());
  const btcore::SeriesBatch batch(universe.values, universe.offsets);
  std::vector<double> alone(universe.values.size());
  std::vector<double> spread(universe.values.size());
  btcore::sma(batch, 20, alone, 1);
  btcore::sma(batch, 20, spread, 8);
  expect_identical(spread, alone);
  std::vector<double> single(120);
  btcore::sma(batch.series(7), 20, single);
  expect_identical(single, {alone.begin() + 7 * 120, alone.begin() + 8 * 120});
}

}  // namespace
