#pragma once

#include <cstddef>
#include <cstdint>

#include "series_generators.hpp"

namespace btcore::testing {

// The size of the full history: about six thousand series of ten years of trading days.
inline constexpr std::size_t kHistorySeries = 6'000;
inline constexpr std::size_t kHistoryBars = 2'500;
inline constexpr std::uint64_t kHistorySeed = 2'500;

/// The benchmarks' universe, drawn once from a fixed seed so every run measures the same series.
inline const Universe& full_history() {
  static const auto history = universe(kHistorySeries, kHistoryBars, kHistorySeed);
  return history;
}

}  // namespace btcore::testing
