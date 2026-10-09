#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::testing::expect_identical;
using btcore::testing::kPropertyPeriods;
using btcore::testing::SeriesCase;

constexpr double kWidth = 2.0;

TEST(PriceBandsProperties, BatchEqualsStreaming) {
  const auto seed = btcore::testing::property_seed();
  for (const int period : kPropertyPeriods) {
    for (const SeriesCase& series : btcore::testing::window_cases(period, seed)) {
      SCOPED_TRACE("seed " + std::to_string(seed) + ", period " + std::to_string(period) + ", " +
                   series.label);
      std::vector<double> upper(series.values.size());
      std::vector<double> lower(series.values.size());
      btcore::bollinger_bands(series.values, period, kWidth, upper, lower);
      btcore::BollingerState state(period, kWidth);
      std::vector<double> streamed_upper;
      std::vector<double> streamed_lower;
      for (const double value : series.values) {
        const btcore::Band band = state.update(value);
        streamed_upper.push_back(band.upper);
        streamed_lower.push_back(band.lower);
      }
      expect_identical(upper, streamed_upper);
      expect_identical(lower, streamed_lower);
    }
  }
}

// The lines sit the same distance either side of the simple moving average.
TEST(PriceBandsProperties, TheLinesStraddleTheAverage) {
  const auto seed = btcore::testing::property_seed();
  for (const SeriesCase& series : btcore::testing::window_cases(20, seed)) {
    SCOPED_TRACE("seed " + std::to_string(seed) + ", " + series.label);
    std::vector<double> upper(series.values.size());
    std::vector<double> lower(series.values.size());
    std::vector<double> average(series.values.size());
    btcore::bollinger_bands(series.values, 20, kWidth, upper, lower);
    btcore::sma(series.values, 20, average);
    for (std::size_t index = 0; index < average.size(); ++index) {
      ASSERT_EQ(std::isnan(upper[index]), std::isnan(average[index])) << "index " << index;
      if (!std::isnan(average[index])) {
        ASSERT_GE(upper[index], average[index]) << "index " << index;
        ASSERT_LE(lower[index], average[index]) << "index " << index;
        ASSERT_NEAR((upper[index] + lower[index]) / 2, average[index], 1e-15 * average[index]);
      }
    }
  }
}

TEST(PriceBandsProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) {
        std::vector<double> lower(out.size());
        btcore::bollinger_bands(batch, 20, kWidth, out, lower, threads);
      },
      [](auto values, auto out) {
        std::vector<double> lower(out.size());
        btcore::bollinger_bands(values, 20, kWidth, out, lower);
      });
}

}  // namespace
