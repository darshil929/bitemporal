#pragma once

#include <array>
#include <btcore/types.hpp>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string_view>

namespace btcore {

/// The columns of the daily features the engine computes, in the order `daily_features` writes
/// them.
enum class Feature : std::size_t {
  change_1d,
  return_1d,
  return_1w,
  return_1m,
  return_3m,
  return_6m,
  return_1y,
  momentum_12_1,
  volatility_20d,
  rsi_14,
  adtv_20d,
  volume_ratio_20d,
  delivery_pct_1d,
  delivery_pct_20d,
  from_52w_high,
  is_52w_high,
  is_52w_low,
  sma_20,
  sma_50,
  sma_200,
  ema_20,
  ema_50,
  bollinger_20_upper,
  bollinger_20_lower,
};

/// A column's name and the number of its leading outputs a window cannot fill on a series with no
/// missing input.
struct FeatureColumn {
  std::string_view name;
  int leading_blanks;
};

/// Every column, indexed by `Feature`.
// clang-format off
inline constexpr std::array<FeatureColumn, 24> feature_columns{{
    {"change_1d", 1},
    {"return_1d", 1},
    {"return_1w", 5},
    {"return_1m", 21},
    {"return_3m", 63},
    {"return_6m", 126},
    {"return_1y", 252},
    {"momentum_12_1", 252},
    {"volatility_20d", 20},
    {"rsi_14", 14},
    {"adtv_20d", 19},
    {"volume_ratio_20d", 20},
    {"delivery_pct_1d", 0},
    {"delivery_pct_20d", 19},
    {"from_52w_high", 251},
    {"is_52w_high", 251},
    {"is_52w_low", 251},
    {"sma_20", 19},
    {"sma_50", 49},
    {"sma_200", 199},
    {"ema_20", 19},
    {"ema_50", 49},
    {"bollinger_20_upper", 19},
    {"bollinger_20_lower", 19},
}};
// clang-format on

inline constexpr std::size_t feature_count = feature_columns.size();

/// One instrument's daily bars at one venue, each input holding a value per bar. Close, high and
/// low are multiplied by the adjustment factor, volume and delivery divided by it; turnover is as
/// traded, and delivery is missing on a day without a published figure.
struct DailyBars {
  std::span<const double> close;
  std::span<const double> high;
  std::span<const double> low;
  std::span<const double> volume;
  std::span<const double> delivery;
  std::span<const double> turnover;
  std::span<const double> adjustment_factor;
};

/// Every column of every bar, column `f` of bar `i` at `out[f * n + i]` for `n` bars. Returns,
/// volatility, momentum and the distance from the high are fractions, and the flags 1 or 0;
/// `change_1d`, the averages and the bands are divided by the bar's adjustment factor, so each is
/// in its own day's price scale.
void daily_features(const DailyBars& bars, std::span<double> out);

/// The batch form over every series the offsets mark in the inputs, across threads: column `f` of
/// bar `i` at `out[f * n + i]`, `n` counting the bars of every series.
void daily_features(const DailyBars& bars, std::span<const std::int64_t> offsets,
                    std::span<double> out, unsigned threads);

}  // namespace btcore
