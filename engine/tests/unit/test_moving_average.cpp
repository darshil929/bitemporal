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

std::vector<double> sma(const std::vector<double>& values, int period) {
  std::vector<double> out(values.size());
  btcore::sma(values, period, out);
  return out;
}

// (1 + 2 + 3) / 3 = 2, (2 + 3 + 4) / 3 = 3, (3 + 4 + 5) / 3 = 4.
TEST(Sma, AveragesTheLastPeriodValues) {
  expect_series(sma({1, 2, 3, 4, 5}, 3), {missing, missing, 2, 3, 4});
}

// Each window holding the missing third value is missing: (4 + 5) / 2 = 4.5, (5 + 6) / 2 = 5.5.
TEST(Sma, LeavesEveryWindowHoldingAMissingValueMissing) {
  expect_series(sma({1, 2, kNaN, 4, 5, 6}, 2), {missing, 1.5, missing, missing, 4.5, 5.5});
}

TEST(MovingAverage, LeavesASeriesShorterThanThePeriodMissing) {
  expect_series(sma({4, 5}, 3), {missing, missing});
  expect_series(sma({}, 3), {});
}

TEST(MovingAverage, RefusesAPeriodBelowOneAndAMismatchedOutput) {
  std::vector<double> values{1, 2, 3};
  std::vector<double> short_out(2);
  EXPECT_THROW(btcore::sma(values, 0, short_out), btcore::InvalidArgument);
  EXPECT_THROW(btcore::sma(values, 2, short_out), btcore::InvalidArgument);
  EXPECT_THROW(btcore::SmaState(-1), btcore::InvalidArgument);
}

}  // namespace
