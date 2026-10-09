#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <limits>
#include <vector>

namespace {

using btcore::missing;

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

void expect_series(const std::vector<double>& actual, const std::vector<double>& expected) {
  ASSERT_EQ(actual.size(), expected.size());
  for (std::size_t index = 0; index < expected.size(); ++index) {
    if (std::isnan(expected[index])) {
      EXPECT_TRUE(std::isnan(actual[index])) << "index " << index;
    } else {
      EXPECT_DOUBLE_EQ(actual[index], expected[index]) << "index " << index;
    }
  }
}

std::vector<double> rsi(const std::vector<double>& values, int period) {
  std::vector<double> out(values.size());
  btcore::rsi(values, period, out);
  return out;
}

// Changes +1, -0.5, +1, +0.5, -1. Seeded with gain (1 + 0 + 1) / 3 = 2/3 and loss 0.5 / 3 = 1/6:
// 100 * (2/3) / (5/6) = 80. Then gain (2/3 * 2 + 0.5) / 3 = 11/18, loss (1/6 * 2) / 3 = 2/18:
// 1100 / 13. Then gain (11/18 * 2) / 3 = 11/27, loss (2/18 * 2 + 1) / 3 = 11/27: 50.
TEST(Rsi, SmoothsGainsAndLossesWilderStyle) {
  expect_series(rsi({10, 11, 10.5, 11.5, 12, 11}, 3),
                {missing, missing, missing, 80, 1100.0 / 13, 50});
}

// No change in the first three values leaves nothing to measure. The rise of 1 gives gain 1/2 and
// loss 0: 100. The fall of 2 gives gain 1/4 and loss 1: 100 * 0.25 / 1.25 = 20.
TEST(Rsi, StaysMissingUntilTheSeriesFirstMoves) {
  expect_series(rsi({5, 5, 5, 5, 6, 4}, 2), {missing, missing, missing, missing, 100, 20});
}

// After the missing value the warm-up starts again from 4: changes +2 and -1 give gain 1 and loss
// 1/2, so 100 * 1 / 1.5 = 200/3.
TEST(Rsi, StartsItsWarmUpAgainAfterAMissingValue) {
  expect_series(rsi({1, 2, 3, kNaN, 4, 6, 5}, 2),
                {missing, missing, 100, missing, missing, missing, 200.0 / 3});
}

TEST(Rsi, LeavesASeriesWithoutPeriodChangesMissing) {
  expect_series(rsi({4, 5, 6}, 3), {missing, missing, missing});
  expect_series(rsi({}, 3), {});
}

TEST(Rsi, RefusesAPeriodBelowOneAndAMismatchedOutput) {
  std::vector<double> values{1, 2, 3};
  std::vector<double> short_out(2);
  EXPECT_THROW(btcore::rsi(values, 0, short_out), btcore::InvalidArgument);
  EXPECT_THROW(btcore::rsi(values, 2, short_out), btcore::InvalidArgument);
  EXPECT_THROW(btcore::RsiState(0), btcore::InvalidArgument);
}

}  // namespace
