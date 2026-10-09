#pragma once

#include <gtest/gtest.h>

#include <btcore/types.hpp>
#include <cmath>
#include <span>
#include <string>
#include <vector>

#include "golden_table.hpp"

namespace btcore::testing {

// A family's references agree within its tolerance, 1e-12 relative unless the generator states
// another; the engine is held to the same.
inline constexpr double kGoldenTolerance = 1e-12;

/// Runs `compute(batch, out)` over the closes of every golden series and compares the output with
/// one column of a family's expected file.
template <typename Compute>
void expect_matches_golden(const std::string& file, const std::string& column, Compute compute,
                           double tolerance = kGoldenTolerance) {
  const auto input = GoldenTable::read("golden_ohlcv.csv");
  const auto expected = GoldenTable::read(file);
  const auto offsets = input.series_offsets();
  const SeriesBatch batch(input.numbers("close"), offsets);
  std::vector<double> out(input.rows());
  compute(batch, std::span<double>(out));
  const auto& reference = expected.numbers(column);
  const auto& series = input.text("series");
  const auto& dates = input.text("trade_date");
  ASSERT_EQ(out.size(), reference.size());
  for (std::size_t row = 0; row < out.size(); ++row) {
    SCOPED_TRACE(column + " " + series[row] + " " + dates[row]);
    if (std::isnan(reference[row])) {
      ASSERT_TRUE(std::isnan(out[row]));
    } else {
      ASSERT_NEAR(out[row], reference[row], tolerance * std::fabs(reference[row]));
    }
  }
}

}  // namespace btcore::testing
