#include <gtest/gtest.h>

#include <algorithm>
#include <btcore/types.hpp>
#include <cmath>
#include <string>
#include <vector>

#include "golden_table.hpp"

namespace {

using btcore::testing::GoldenTable;

const std::vector<std::string> kSeries{"hdfc_bank_nse", "reliance_bse",      "shriram_finance_nse",
                                       "spicejet_bse",  "vodafone_idea_nse", "infosys_nse",
                                       "flat_40",       "ten_bars"};

TEST(GoldenInput, HoldsEverySeriesInOrderAsABatch) {
  const auto input = GoldenTable::read("golden_ohlcv.csv");
  EXPECT_EQ(input.series_names(), kSeries);
  const auto offsets = input.series_offsets();
  const btcore::SeriesBatch batch(input.numbers("close"), offsets);
  ASSERT_EQ(batch.size(), kSeries.size());
  for (std::size_t index = 0; index < 6; ++index) {
    EXPECT_EQ(batch.series(index).size(), 498U) << kSeries[index];
  }
  EXPECT_EQ(batch.series(6).size(), 40U);
  EXPECT_EQ(batch.series(7).size(), 10U);
}

TEST(GoldenInput, ReadsAnEmptyFieldAsMissing) {
  const auto input = GoldenTable::read("golden_ohlcv.csv");
  const auto& delivery = input.numbers("delivery");
  EXPECT_TRUE(btcore::is_missing(delivery.front()));
  EXPECT_FALSE(btcore::is_missing(delivery[497]));
  const auto& factor = input.numbers("factor");
  EXPECT_TRUE(std::all_of(factor.begin(), factor.end(), [](double value) { return value > 0.0; }));
}

TEST(GoldenExpected, AlignsRowForRowWithTheInput) {
  const auto input = GoldenTable::read("golden_ohlcv.csv");
  const auto expected = GoldenTable::read("golden_moving_averages.csv");
  ASSERT_EQ(expected.rows(), input.rows());
  EXPECT_EQ(expected.text("series"), input.text("series"));
  EXPECT_EQ(expected.text("trade_date"), input.text("trade_date"));
}

TEST(GoldenTable, RefusesAFileItCannotRead) {
  EXPECT_THROW(static_cast<void>(GoldenTable::read("absent.csv")), std::runtime_error);
}

}  // namespace
