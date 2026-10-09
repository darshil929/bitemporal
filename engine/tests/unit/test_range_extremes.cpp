#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <limits>
#include <vector>

namespace {

using btcore::Extreme;
using btcore::missing;

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

void expect_series(const std::vector<double>& actual, const std::vector<double>& expected) {
  ASSERT_EQ(actual.size(), expected.size());
  for (std::size_t index = 0; index < expected.size(); ++index) {
    if (std::isnan(expected[index])) {
      EXPECT_TRUE(std::isnan(actual[index])) << "index " << index;
    } else {
      EXPECT_EQ(actual[index], expected[index]) << "index " << index;
    }
  }
}

std::vector<double> extreme(const std::vector<double>& values, int period, Extreme kind) {
  std::vector<double> out(values.size());
  btcore::rolling_extreme(values, period, kind, out);
  return out;
}

// The 5 stays the maximum until it leaves after three bars; the 1 the minimum until it leaves.
TEST(RollingExtreme, KeepsTheLargestOrSmallestOfTheWindow) {
  const std::vector<double> values{3, 5, 1, 4, 2, 2, 6};
  expect_series(extreme(values, 3, Extreme::maximum), {missing, missing, 5, 5, 4, 4, 6});
  expect_series(extreme(values, 3, Extreme::minimum), {missing, missing, 1, 1, 1, 2, 2});
}

TEST(RollingExtreme, LeavesEveryWindowHoldingAMissingValueMissing) {
  expect_series(extreme({1, 2, kNaN, 4, 5, 3}, 2, Extreme::maximum),
                {missing, 2, missing, missing, 5, 5});
}

TEST(RollingExtreme, ReturnsTheValueItselfForAPeriodOfOne) {
  expect_series(extreme({3, -1, 7}, 1, Extreme::minimum), {3, -1, 7});
  expect_series(extreme({4, 5}, 3, Extreme::maximum), {missing, missing});
}

TEST(RollingExtreme, RefusesAPeriodBelowOneAndAMismatchedOutput) {
  std::vector<double> values{1, 2, 3};
  std::vector<double> short_out(2);
  EXPECT_THROW(btcore::rolling_extreme(values, 0, Extreme::maximum, values),
               btcore::InvalidArgument);
  EXPECT_THROW(btcore::rolling_extreme(values, 2, Extreme::maximum, short_out),
               btcore::InvalidArgument);
  EXPECT_THROW(btcore::RollingExtremeState(-3, Extreme::minimum), btcore::InvalidArgument);
}

}  // namespace
