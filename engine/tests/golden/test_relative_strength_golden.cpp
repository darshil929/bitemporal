#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <string>

#include "golden_checks.hpp"

namespace {

using btcore::testing::expect_matches_golden;

TEST(RelativeStrengthGolden, RsiMatchesTheReference) {
  for (const int period : {2, 14}) {
    expect_matches_golden("golden_relative_strength.csv", "rsi_" + std::to_string(period),
                          [&](const auto& batch, auto out) { btcore::rsi(batch, period, out, 0); });
  }
}

}  // namespace
