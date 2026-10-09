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

// 300 over the mean of 100 and 200 is 2; 50 over the mean of 200 and 300 is 0.2.
TEST(RatioToPriorMean, DividesEachValueByTheMeanBeforeIt) {
  std::vector<double> out(4);
  btcore::ratio_to_prior_mean(std::vector<double>{100, 200, 300, 50}, 2, out);
  expect_series(out, {missing, missing, 2, 0.2});
}

TEST(RatioToPriorMean, LeavesARatioOverAMissingValueMissing) {
  std::vector<double> out(5);
  btcore::ratio_to_prior_mean(std::vector<double>{100, kNaN, 300, 400, 700}, 2, out);
  expect_series(out, {missing, missing, missing, missing, 2});
}

TEST(PercentageOf, TakesEachPartOfItsWholeAndLeavesAMissingPartMissing) {
  std::vector<double> out(3);
  btcore::percentage_of(std::vector<double>{25, kNaN, 300}, std::vector<double>{50, 10, 200}, out);
  expect_series(out, {50, missing, 150});
}

TEST(TradedValue, RefusesAPeriodBelowOneAndMismatchedLengths) {
  std::vector<double> values{1, 2, 3};
  std::vector<double> short_out(2);
  EXPECT_THROW(btcore::ratio_to_prior_mean(values, 0, values), btcore::InvalidArgument);
  EXPECT_THROW(btcore::ratio_to_prior_mean(values, 1, short_out), btcore::InvalidArgument);
  EXPECT_THROW(btcore::percentage_of(values, short_out, values), btcore::InvalidArgument);
}

}  // namespace
