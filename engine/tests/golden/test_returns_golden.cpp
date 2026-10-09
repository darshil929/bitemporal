#include <gtest/gtest.h>

#include <btcore/indicators.hpp>

#include "golden_checks.hpp"

namespace {

using btcore::testing::expect_matches_golden;

TEST(ReturnsGolden, ReturnsMatchTheReference) {
  expect_matches_golden("golden_returns.csv", "return_1", [](const auto& batch, auto out) {
    btcore::simple_return(batch, 1, 0, out, 0);
  });
  expect_matches_golden("golden_returns.csv", "return_252", [](const auto& batch, auto out) {
    btcore::simple_return(batch, 252, 0, out, 0);
  });
  expect_matches_golden("golden_returns.csv", "momentum_12_1", [](const auto& batch, auto out) {
    btcore::simple_return(batch, 231, 21, out, 0);
  });
}

}  // namespace
