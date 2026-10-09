#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <vector>

#include "golden_checks.hpp"

namespace {

using btcore::testing::expect_matches_golden;

TEST(PriceBandsGolden, BollingerBandsMatchTheReference) {
  expect_matches_golden("golden_price_bands.csv", "bollinger_20_upper",
                        [](const auto& batch, auto out) {
                          std::vector<double> lower(out.size());
                          btcore::bollinger_bands(batch, 20, 2.0, out, lower, 0);
                        });
  expect_matches_golden("golden_price_bands.csv", "bollinger_20_lower",
                        [](const auto& batch, auto out) {
                          std::vector<double> upper(out.size());
                          btcore::bollinger_bands(batch, 20, 2.0, upper, out, 0);
                        });
}

}  // namespace
