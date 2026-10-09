#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <vector>

#include "golden_checks.hpp"
#include "golden_table.hpp"

namespace {

using btcore::testing::expect_matches_golden;
using btcore::testing::kGoldenTolerance;

TEST(TradedValueGolden, TradedValueAndDeliveryMatchTheReference) {
  const auto input = btcore::testing::GoldenTable::read("golden_ohlcv.csv");
  const auto& volumes = input.numbers("volume");
  const auto offsets = input.series_offsets();
  expect_matches_golden(
      "golden_traded_value.csv", "adtv_20",
      [](const auto& batch, auto out) { btcore::sma(batch, 20, out, 0); }, kGoldenTolerance,
      "turnover");
  expect_matches_golden(
      "golden_traded_value.csv", "volume_ratio_20",
      [](const auto& batch, auto out) { btcore::ratio_to_prior_mean(batch, 20, out, 0); },
      kGoldenTolerance, "volume");
  expect_matches_golden(
      "golden_traded_value.csv", "delivery_pct_1",
      [&volumes](const auto& batch, auto out) {
        btcore::percentage_of(batch.values(), volumes, out);
      },
      kGoldenTolerance, "delivery");
  expect_matches_golden(
      "golden_traded_value.csv", "delivery_pct_20",
      [&volumes, &offsets](const auto& batch, auto out) {
        std::vector<double> daily(out.size());
        btcore::percentage_of(batch.values(), volumes, daily);
        btcore::sma(btcore::SeriesBatch(daily, offsets), 20, out, 0);
      },
      kGoldenTolerance, "delivery");
}

}  // namespace
