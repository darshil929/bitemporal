#include <gtest/gtest.h>

#include <algorithm>
#include <btcore/indicators.hpp>
#include <cmath>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::Extreme;
using btcore::testing::expect_batch_equals_streaming;
using btcore::testing::kPropertyPeriods;
using btcore::testing::SeriesCase;

template <Extreme kind>
struct ExtremeState : btcore::RollingExtremeState {
  explicit ExtremeState(int period) : RollingExtremeState(period, kind) {}
};

constexpr auto kWindowBlanks = [](int period) { return period - 1; };

TEST(RangeExtremesProperties, BatchEqualsStreaming) {
  expect_batch_equals_streaming<ExtremeState<Extreme::maximum>>(
      [](std::span<const double> v, int p, std::span<double> o) {
        btcore::rolling_extreme(v, p, Extreme::maximum, o);
      },
      kWindowBlanks);
  expect_batch_equals_streaming<ExtremeState<Extreme::minimum>>(
      [](std::span<const double> v, int p, std::span<double> o) {
        btcore::rolling_extreme(v, p, Extreme::minimum, o);
      },
      kWindowBlanks);
}

// The queue gives what a scan of each whole window gives.
TEST(RangeExtremesProperties, EqualsAScanOfEachWindow) {
  const auto seed = btcore::testing::property_seed();
  for (const int period : kPropertyPeriods) {
    for (const SeriesCase& series : btcore::testing::window_cases(period, seed)) {
      SCOPED_TRACE("seed " + std::to_string(seed) + ", period " + std::to_string(period) + ", " +
                   series.label);
      std::vector<double> highest(series.values.size());
      std::vector<double> lowest(series.values.size());
      btcore::rolling_extreme(series.values, period, Extreme::maximum, highest);
      btcore::rolling_extreme(series.values, period, Extreme::minimum, lowest);
      const auto window = static_cast<std::size_t>(period);
      for (std::size_t end = window; end <= series.values.size(); ++end) {
        const auto first = series.values.begin() + static_cast<std::ptrdiff_t>(end - window);
        const auto last = series.values.begin() + static_cast<std::ptrdiff_t>(end);
        if (std::any_of(first, last, [](double value) { return std::isnan(value); })) {
          ASSERT_TRUE(std::isnan(highest[end - 1]) && std::isnan(lowest[end - 1]));
        } else {
          ASSERT_EQ(highest[end - 1], *std::max_element(first, last)) << "end " << end;
          ASSERT_EQ(lowest[end - 1], *std::min_element(first, last)) << "end " << end;
        }
      }
    }
  }
}

TEST(RangeExtremesProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) {
        btcore::rolling_extreme(batch, 20, Extreme::maximum, out, threads);
      },
      [](auto values, auto out) { btcore::rolling_extreme(values, 20, Extreme::maximum, out); });
}

}  // namespace
