#include <gtest/gtest.h>

#include <algorithm>
#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <cmath>
#include <cstddef>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::testing::kPropertyPeriods;
using btcore::testing::SeriesCase;

std::vector<double> rsi_of(const std::vector<double>& values, int period) {
  std::vector<double> out(values.size());
  btcore::rsi(values, period, out);
  return out;
}

TEST(RelativeStrengthProperties, RsiBatchEqualsStreaming) {
  btcore::testing::expect_batch_equals_streaming<btcore::RsiState>(
      [](std::span<const double> v, int p, std::span<double> o) { btcore::rsi(v, p, o); },
      [](int period) { return period; });
}

TEST(RelativeStrengthProperties, RsiStaysBetweenZeroAndOneHundred) {
  const auto seed = btcore::testing::property_seed();
  for (const int period : kPropertyPeriods) {
    for (const SeriesCase& series : btcore::testing::window_cases(period, seed)) {
      SCOPED_TRACE("seed " + std::to_string(seed) + ", period " + std::to_string(period) + ", " +
                   series.label);
      for (const double value : rsi_of(series.values, period)) {
        if (!std::isnan(value)) {
          ASSERT_GE(value, 0.0);
          ASSERT_LE(value, 100.0);
        }
      }
    }
  }
}

// A flat start leaves no movement to measure; the first change decides the reading.
TEST(RelativeStrengthProperties, AFlatStartStaysBlankThenRisingReadsOneHundred) {
  constexpr std::size_t kFlatBars = 20;
  std::vector<double> rising(kFlatBars, 50.0);
  std::vector<double> falling(kFlatBars, 50.0);
  for (std::size_t step = 1; step <= 30; ++step) {
    rising.push_back(50.0 + static_cast<double>(step));
    falling.push_back(50.0 - static_cast<double>(step));
  }
  for (const int period : kPropertyPeriods) {
    const auto up = rsi_of(rising, period);
    const auto down = rsi_of(falling, period);
    const auto first = std::max(kFlatBars, static_cast<std::size_t>(period));
    for (std::size_t index = 0; index < up.size(); ++index) {
      if (index < first) {
        ASSERT_TRUE(std::isnan(up[index]) && std::isnan(down[index])) << period << " " << index;
      } else {
        ASSERT_EQ(up[index], 100.0) << period << " " << index;
        ASSERT_EQ(down[index], 0.0) << period << " " << index;
      }
    }
  }
}

TEST(RelativeStrengthProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) { btcore::rsi(batch, 14, out, threads); },
      [](auto values, auto out) { btcore::rsi(values, 14, out); });
}

}  // namespace
