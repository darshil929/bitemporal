#pragma once

#include <gtest/gtest.h>

#include <algorithm>
#include <bit>
#include <btcore/types.hpp>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <span>
#include <string>
#include <vector>

#include "series_generators.hpp"

namespace btcore::testing {

inline constexpr int kPropertyPeriods[] = {1, 2, 14, 20};

template <typename State>
std::vector<double> streamed(const std::vector<double>& values, int period) {
  State state(period);
  std::vector<double> out;
  out.reserve(values.size());
  for (const double value : values) {
    out.push_back(state.update(value));
  }
  return out;
}

/// Equal bit for bit, a missing value equal to a missing value.
inline void expect_identical(std::span<const double> actual, std::span<const double> expected) {
  ASSERT_EQ(actual.size(), expected.size());
  for (std::size_t index = 0; index < expected.size(); ++index) {
    ASSERT_EQ(std::bit_cast<std::uint64_t>(actual[index]),
              std::bit_cast<std::uint64_t>(expected[index]))
        << "index " << index << ": " << actual[index] << " against " << expected[index];
  }
}

/// Over every window case of every period: `batch(values, period, out)` equals the streaming form
/// bit for bit, and its first `leading_blanks(period)` outputs are missing.
template <typename State, typename Batch, typename LeadingBlanks>
void expect_batch_equals_streaming(Batch batch, LeadingBlanks leading_blanks,
                                   std::span<const int> periods = kPropertyPeriods) {
  const auto seed = property_seed();
  for (const int period : periods) {
    for (const SeriesCase& series : window_cases(period, seed)) {
      SCOPED_TRACE("seed " + std::to_string(seed) + ", period " + std::to_string(period) + ", " +
                   series.label);
      std::vector<double> out(series.values.size());
      batch(series.values, period, out);
      expect_identical(out, streamed<State>(series.values, period));
      const auto blanks = std::min(static_cast<std::size_t>(leading_blanks(period)), out.size());
      EXPECT_TRUE(std::all_of(out.begin(), out.begin() + static_cast<std::ptrdiff_t>(blanks),
                              [](double value) { return std::isnan(value); }));
    }
  }
}

/// `universe_form(batch, out, threads)` gives the same output on one thread and on eight, and each
/// series' part equals `series_form(values, out)` on that series alone.
template <typename Universe, typename Series>
void expect_universe_matches_each_series(Universe universe_form, Series series_form) {
  constexpr std::size_t kLength = 120;
  const auto drawn = universe(300, kLength, property_seed());
  const SeriesBatch batch(drawn.values, drawn.offsets);
  std::vector<double> alone(drawn.values.size());
  std::vector<double> spread(drawn.values.size());
  universe_form(batch, std::span<double>(alone), 1U);
  universe_form(batch, std::span<double>(spread), 8U);
  expect_identical(spread, alone);
  std::vector<double> single(kLength);
  series_form(batch.series(7), std::span<double>(single));
  expect_identical(single, std::span<const double>(alone).subspan(7 * kLength, kLength));
}

}  // namespace btcore::testing
