#include <gtest/gtest.h>

#include <btcore/indicators.hpp>

#include "golden_checks.hpp"
#include "golden_table.hpp"

namespace {

TEST(VolumeFlowGolden, OnBalanceVolumeMatchesTheReference) {
  const auto input = btcore::testing::GoldenTable::read("golden_ohlcv.csv");
  const auto& volumes = input.numbers("volume");
  btcore::testing::expect_matches_golden("golden_volume_flow.csv", "obv",
                                         [&volumes](const auto& batch, auto out) {
                                           btcore::on_balance_volume(batch, volumes, out, 0);
                                         });
}

}  // namespace
