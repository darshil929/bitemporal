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

// Each input a different multiple of a drawn series with values missing, so no column can read
// another's input unnoticed.
TEST(FeaturesProperties, BatchEqualsStreaming) {
  constexpr std::size_t kLength = 300;
  const auto seed = btcore::testing::property_seed();
  SCOPED_TRACE("seed " + std::to_string(seed));
  auto drawn = btcore::testing::universe(10, kLength, seed + 2);
  btcore::testing::SeriesGenerator(seed + 2).punch_gaps(drawn.values, 10);
  const std::span<const double> values = drawn.values;
  std::vector<double> factor(kLength, 1.0);
  std::fill_n(factor.begin(), kLength / 2, 0.5);
  for (std::size_t first = 0; first < values.size(); first += kLength) {
    std::vector<double> close, high, low, volume, delivery, turnover;
    btcore::DailyFeatureState state;
    std::vector<double> streamed(kLength * btcore::feature_count);
    for (std::size_t bar = 0; bar < kLength; ++bar) {
      const double value = values[first + bar];
      const btcore::DailyBar daily{value,       value * 1.01, value * 0.99, value * 7.0,
                                   value * 3.0, value * 11.0, factor[bar]};
      close.push_back(daily.close);
      high.push_back(daily.high);
      low.push_back(daily.low);
      volume.push_back(daily.volume);
      delivery.push_back(daily.delivery);
      turnover.push_back(daily.turnover);
      const auto row = state.update(daily);
      for (std::size_t feature = 0; feature < btcore::feature_count; ++feature) {
        streamed[feature * kLength + bar] = row[feature];
      }
    }
    std::vector<double> batch(streamed.size());
    btcore::daily_features({close, high, low, volume, delivery, turnover, factor}, batch);
    expect_identical(streamed, batch);
  }
}

}  // namespace
