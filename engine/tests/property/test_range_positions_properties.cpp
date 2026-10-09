#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::Extreme;
using btcore::testing::expect_identical;
using btcore::testing::kPropertyPeriods;
using btcore::testing::SeriesCase;

template <Extreme kind>
struct NewExtremeOf : btcore::NewExtremeState {
  explicit NewExtremeOf(int period) : NewExtremeState(period, kind) {}
};

TEST(RangePositionsProperties, BatchEqualsStreaming) {
  btcore::testing::expect_batch_equals_streaming<NewExtremeOf<Extreme::maximum>>(
      [](std::span<const double> v, int p, std::span<double> o) {
        btcore::new_extreme(v, p, Extreme::maximum, o);
      },
      [](int period) { return period - 1; });
  const auto seed = btcore::testing::property_seed();
  for (const int period : kPropertyPeriods) {
    for (const SeriesCase& series : btcore::testing::window_cases(period, seed)) {
      SCOPED_TRACE("seed " + std::to_string(seed) + ", period " + std::to_string(period) + ", " +
                   series.label);
      std::vector<double> highs(series.values);
      for (double& high : highs) {
        high *= 1.25;
      }
      std::vector<double> batch(series.values.size());
      btcore::distance_from_high(series.values, highs, period, batch);
      btcore::HighDistanceState state(period);
      std::vector<double> streamed;
      for (std::size_t index = 0; index < highs.size(); ++index) {
        streamed.push_back(state.update(series.values[index], highs[index]));
      }
      expect_identical(batch, streamed);
    }
  }
}

// A close never rises above the highest high, so the distance lies between -1 and 0.
TEST(RangePositionsProperties, TheDistanceStaysWithinMinusOneAndZero) {
  const auto seed = btcore::testing::property_seed();
  for (const SeriesCase& series : btcore::testing::window_cases(20, seed)) {
    std::vector<double> out(series.values.size());
    btcore::distance_from_high(series.values, series.values, 20, out);
    for (const double value : out) {
      ASSERT_TRUE(std::isnan(value) || (value <= 0.0 && value > -1.0))
          << "seed " << seed << ", " << series.label;
    }
  }
}

TEST(RangePositionsProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) {
        btcore::distance_from_high(batch, batch.values(), 20, out, threads);
      },
      [](auto values, auto out) { btcore::distance_from_high(values, values, 20, out); });
}

}  // namespace
