#include <gtest/gtest.h>

#include <btcore/indicators.hpp>

#include "golden_checks.hpp"

namespace {

TEST(VolatilityGolden, RealisedVolatilityMatchesTheReference) {
  btcore::testing::expect_matches_golden(
      "golden_volatility.csv", "volatility_20",
      [](const auto& batch, auto out) { btcore::realised_volatility(batch, 20, 252, out, 0); });
}

}  // namespace
