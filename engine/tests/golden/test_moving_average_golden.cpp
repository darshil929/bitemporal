#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <cmath>
#include <string>
#include <vector>

#include "golden_table.hpp"

namespace {

using btcore::testing::GoldenTable;

// The references agree within 1e-12 relative; the engine is held to the same.
constexpr double kTolerance = 1e-12;

void expect_matches(const std::string& column, const std::vector<double>& out) {
  const auto input = GoldenTable::read("golden_ohlcv.csv");
  const auto expected = GoldenTable::read("golden_moving_averages.csv");
  const auto& reference = expected.numbers(column);
  const auto& series = input.text("series");
  const auto& dates = input.text("trade_date");
  ASSERT_EQ(out.size(), reference.size());
  for (std::size_t row = 0; row < out.size(); ++row) {
    SCOPED_TRACE(column + " " + series[row] + " " + dates[row]);
    if (std::isnan(reference[row])) {
      ASSERT_TRUE(std::isnan(out[row]));
    } else {
      ASSERT_NEAR(out[row], reference[row], kTolerance * std::fabs(reference[row]));
    }
  }
}

TEST(MovingAverageGolden, SmaMatchesTheReference) {
  const auto input = GoldenTable::read("golden_ohlcv.csv");
  const auto offsets = input.series_offsets();
  const btcore::SeriesBatch batch(input.numbers("close"), offsets);
  for (const int period : {20, 50, 200}) {
    std::vector<double> out(input.rows());
    btcore::sma(batch, period, out, 0);
    expect_matches("sma_" + std::to_string(period), out);
  }
}

}  // namespace
