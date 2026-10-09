#include <gtest/gtest.h>

#include <btcore/indicators.hpp>

#include "golden_checks.hpp"

namespace {

using btcore::Extreme;
using btcore::testing::expect_matches_golden;
using btcore::testing::kGoldenTolerance;

TEST(RangeExtremesGolden, RollingExtremesMatchTheReference) {
  for (const int period : {20, 252}) {
    expect_matches_golden(
        "golden_range_extremes.csv", "maximum_" + std::to_string(period),
        [period](const auto& batch, auto out) {
          btcore::rolling_extreme(batch, period, Extreme::maximum, out, 0);
        },
        kGoldenTolerance, "high");
  }
  expect_matches_golden(
      "golden_range_extremes.csv", "minimum_20",
      [](const auto& batch, auto out) {
        btcore::rolling_extreme(batch, 20, Extreme::minimum, out, 0);
      },
      kGoldenTolerance, "low");
}

}  // namespace
