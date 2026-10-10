#include <gtest/gtest.h>

#include <btcore/features.hpp>
#include <cstddef>
#include <span>
#include <vector>

#include "golden_checks.hpp"
#include "golden_table.hpp"

namespace {

using btcore::Feature;

struct Reference {
  Feature feature;
  const char* file;
  const char* column;
  bool is_level;
};

// Every column a family holds; the other return windows are the same computation over other
// lengths.
constexpr Reference kReferences[] = {
    {Feature::change_1d, "golden_price_changes.csv", "change_1", true},
    {Feature::return_1d, "golden_returns.csv", "return_1", false},
    {Feature::return_1y, "golden_returns.csv", "return_252", false},
    {Feature::momentum_12_1, "golden_returns.csv", "momentum_12_1", false},
    {Feature::volatility_20d, "golden_volatility.csv", "volatility_20", false},
    {Feature::rsi_14, "golden_relative_strength.csv", "rsi_14", false},
    {Feature::sma_20, "golden_moving_averages.csv", "sma_20", true},
    {Feature::sma_50, "golden_moving_averages.csv", "sma_50", true},
    {Feature::sma_200, "golden_moving_averages.csv", "sma_200", true},
    {Feature::ema_20, "golden_moving_averages.csv", "ema_20", true},
    {Feature::ema_50, "golden_moving_averages.csv", "ema_50", true},
    {Feature::bollinger_20_upper, "golden_price_bands.csv", "bollinger_20_upper", true},
    {Feature::bollinger_20_lower, "golden_price_bands.csv", "bollinger_20_lower", true},
};

// A level's reference is in the adjusted scale, so the engine's is multiplied back by the factor.
TEST(FeaturesGolden, EveryColumnMatchesItsFamily) {
  const auto input = btcore::testing::GoldenTable::read("golden_ohlcv.csv");
  const auto& factor = input.numbers("factor");
  const btcore::DailyBars bars{input.numbers("close"), factor};
  const std::size_t rows = input.rows();
  std::vector<double> features(rows * btcore::feature_count);
  btcore::daily_features(bars, input.series_offsets(), features, 0);
  for (const Reference& reference : kReferences) {
    const auto first = static_cast<std::size_t>(reference.feature) * rows;
    btcore::testing::expect_matches_golden(
        reference.file, reference.column, [&](const auto&, std::span<double> out) {
          for (std::size_t row = 0; row < rows; ++row) {
            out[row] = features[first + row] * (reference.is_level ? factor[row] : 1.0);
          }
        });
  }
}

}  // namespace
