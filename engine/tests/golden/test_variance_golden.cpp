#include <gtest/gtest.h>

#include <btcore/indicators.hpp>

#include "golden_checks.hpp"

namespace {

using btcore::Estimator;
using btcore::testing::expect_matches_golden;

// TA-Lib's running sums stay within 1e-11 of the two-pass variance, and the family is held to it.
constexpr double kVarianceTolerance = 1e-11;

TEST(VarianceGolden, VarianceMatchesTheReference) {
  expect_matches_golden(
      "golden_variance.csv", "variance_20",
      [](const auto& batch, auto out) {
        btcore::variance(batch, 20, Estimator::population, out, 0);
      },
      kVarianceTolerance);
  expect_matches_golden(
      "golden_variance.csv", "sample_variance_20",
      [](const auto& batch, auto out) { btcore::variance(batch, 20, Estimator::sample, out, 0); },
      kVarianceTolerance);
}

}  // namespace
