#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

constexpr int kPeriods[] = {2, 14, 20};

struct YearlyVolatilityState : btcore::VolatilityState {
  explicit YearlyVolatilityState(int period) : VolatilityState(period, 252) {}
};

TEST(VolatilityProperties, BatchEqualsStreaming) {
  btcore::testing::expect_batch_equals_streaming<YearlyVolatilityState>(
      [](std::span<const double> v, int p, std::span<double> o) {
        btcore::realised_volatility(v, p, 252, o);
      },
      [](int period) { return period; }, kPeriods);
}

// Returns, and so the volatility, do not depend on the price level.
TEST(VolatilityProperties, IsNonNegativeAndIndifferentToThePriceLevel) {
  const auto seed = btcore::testing::property_seed();
  for (const auto& series : btcore::testing::window_cases(20, seed)) {
    SCOPED_TRACE("seed " + std::to_string(seed) + ", " + series.label);
    std::vector<double> scaled(series.values);
    for (double& value : scaled) {
      value *= 8.0;
    }
    std::vector<double> out(series.values.size());
    std::vector<double> scaled_out(series.values.size());
    btcore::realised_volatility(series.values, 20, 252, out);
    btcore::realised_volatility(scaled, 20, 252, scaled_out);
    btcore::testing::expect_identical(out, scaled_out);
    for (const double value : out) {
      ASSERT_TRUE(std::isnan(value) || value >= 0.0);
    }
  }
}

TEST(VolatilityProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) {
        btcore::realised_volatility(batch, 20, 252, out, threads);
      },
      [](auto values, auto out) { btcore::realised_volatility(values, 20, 252, out); });
}

}  // namespace
