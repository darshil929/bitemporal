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
inline constexpr std::array<FeatureColumn, 17> feature_columns{{
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
    {"sma_20", 19},
    {"sma_50", 49},
    {"sma_200", 199},
    {"ema_20", 19},
    {"ema_50", 49},
    {"bollinger_20_upper", 19},
    {"bollinger_20_lower", 19},
}};

inline constexpr std::size_t feature_count = feature_columns.size();

/// One instrument's daily bars at one venue: closes multiplied by the adjustment factor, and each
/// bar's factor.
struct DailyBars {
  std::span<const double> close;
  std::span<const double> adjustment_factor;
};

/// Every column of every bar, column `f` of bar `i` at `out[f * n + i]` for `n` bars. Returns,
/// volatility and momentum are fractions; `change_1d`, the averages and the bands are divided by
/// the bar's adjustment factor, so each is in its own day's price scale.
void daily_features(const DailyBars& bars, std::span<double> out);

/// The batch form over every series the offsets mark in the inputs, across threads: column `f` of
/// bar `i` at `out[f * n + i]`, `n` counting the bars of every series.
void daily_features(const DailyBars& bars, std::span<const std::int64_t> offsets,
                    std::span<double> out, unsigned threads);

}  // namespace btcore
