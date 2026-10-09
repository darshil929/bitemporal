#include <gtest/gtest.h>

#include <btcore/indicators.hpp>

#include "golden_checks.hpp"

namespace {

using btcore::testing::expect_matches_golden;

TEST(ReturnsGolden, ChangesMatchTheReference) {
  expect_matches_golden("golden_price_changes.csv", "change_1",
                        [](const auto& batch, auto out) { btcore::change(batch, 1, out, 0); });
}

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
