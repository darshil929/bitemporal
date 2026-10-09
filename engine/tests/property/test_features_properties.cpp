#include <gtest/gtest.h>

#include <algorithm>
#include <btcore/features.hpp>
#include <cstddef>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::testing::expect_identical;

// Drawn series past every window with values missing, read as every input, under a factor that
// steps halfway through each series as a bonus does.
TEST(FeaturesProperties, UniverseEqualsEachSeriesAloneOnAnyThreadCount) {
  constexpr std::size_t kLength = 300;
  const auto seed = btcore::testing::property_seed();
  SCOPED_TRACE("seed " + std::to_string(seed));
  auto drawn = btcore::testing::universe(40, kLength, seed);
  btcore::testing::SeriesGenerator(seed).punch_gaps(drawn.values, 20);
  const std::span<const double> values = drawn.values;
  std::vector<double> factor(values.size(), 1.0);
  for (auto start = factor.begin(); start != factor.end(); start += kLength) {
    std::fill_n(start, kLength / 2, 0.5);
  }
  const btcore::DailyBars bars{values, values, values, values, values, values, factor};
  const std::size_t rows = values.size();
  std::vector<double> alone(rows * btcore::feature_count);
  std::vector<double> spread(rows * btcore::feature_count);
  btcore::daily_features(bars, drawn.offsets, alone, 1);
  btcore::daily_features(bars, drawn.offsets, spread, 8);
  expect_identical(spread, alone);
  for (std::size_t first = 0; first < rows; first += kLength) {
    const auto series = values.subspan(first, kLength);
    const btcore::DailyBars single_bars{series,
                                        series,
                                        series,
                                        series,
                                        series,
                                        series,
                                        std::span<const double>(factor).subspan(first, kLength)};
    std::vector<double> single(kLength * btcore::feature_count);
    btcore::daily_features(single_bars, single);
    for (std::size_t feature = 0; feature < btcore::feature_count; ++feature) {
      expect_identical(std::span<const double>(single).subspan(feature * kLength, kLength),
                       std::span<const double>(alone).subspan(feature * rows + first, kLength));
    }
  }
}

}  // namespace
