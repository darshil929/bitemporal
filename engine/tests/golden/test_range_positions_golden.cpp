#include <gtest/gtest.h>

#include <btcore/indicators.hpp>

#include "golden_checks.hpp"
#include "golden_table.hpp"

namespace {

using btcore::Extreme;
using btcore::testing::expect_matches_golden;
using btcore::testing::kGoldenTolerance;

TEST(RangePositionsGolden, YearlyRangeMeasuresMatchTheReference) {
  const auto input = btcore::testing::GoldenTable::read("golden_ohlcv.csv");
  const auto& highs = input.numbers("high");
  expect_matches_golden("golden_range_positions.csv", "from_52w_high",
                        [&highs](const auto& batch, auto out) {
                          btcore::distance_from_high(batch, highs, 252, out, 0);
                        });
  expect_matches_golden(
      "golden_range_positions.csv", "is_52w_high",
      [](const auto& batch, auto out) {
        btcore::new_extreme(batch, 252, Extreme::maximum, out, 0);
      },
      kGoldenTolerance, "high");
  expect_matches_golden(
      "golden_range_positions.csv", "is_52w_low",
      [](const auto& batch, auto out) {
        btcore::new_extreme(batch, 252, Extreme::minimum, out, 0);
      },
      kGoldenTolerance, "low");
}

}  // namespace
