#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <limits>
#include <vector>

namespace {

using btcore::Estimator;
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

std::vector<double> variance(const std::vector<double>& values, int period, Estimator estimator) {
  std::vector<double> out(values.size());
  btcore::variance(values, period, estimator, out);
  return out;
}

// [1, 2, 3] and [2, 3, 4] deviate by -1, 0, 1: squares 2, so 2/3 and 2/2. [3, 4, 6] has mean 13/3
// and deviations -4/3, -1/3, 5/3: squares 42/9, so 14/9 and 7/3.
TEST(Variance, DividesBySizeOrOneLess) {
  expect_series(variance({1, 2, 3, 4, 6}, 3, Estimator::population),
                {missing, missing, 2.0 / 3, 2.0 / 3, 14.0 / 9});
  expect_series(variance({1, 2, 3, 4, 6}, 3, Estimator::sample), {missing, missing, 1, 1, 7.0 / 3});
}

// Each window holding the missing third value is missing: [4, 5] and [5, 6] deviate by 0.5.
TEST(Variance, LeavesEveryWindowHoldingAMissingValueMissing) {
  expect_series(variance({1, 2, kNaN, 4, 5, 6}, 2, Estimator::population),
                {missing, 0.25, missing, missing, 0.25, 0.25});
}

TEST(Variance, GivesExactlyZeroOnceTheWindowHoldsEqualValues) {
  for (const double level : {0.1, 1'000'000'000.3}) {
    EXPECT_EQ(variance({5, 7, level, level, level}, 3, Estimator::sample)[4], 0.0) << level;
  }
}

TEST(Variance, LeavesASeriesShorterThanThePeriodMissing) {
  expect_series(variance({4, 5}, 3, Estimator::sample), {missing, missing});
  expect_series(variance({}, 3, Estimator::population), {});
}

TEST(Variance, RefusesAPeriodTooShortForItsEstimatorAndAMismatchedOutput) {
  std::vector<double> values{1, 2, 3};
  std::vector<double> short_out(2);
  EXPECT_THROW(btcore::variance(values, 0, Estimator::population, short_out),
               btcore::InvalidArgument);
  EXPECT_THROW(btcore::variance(values, 2, Estimator::population, short_out),
               btcore::InvalidArgument);
  EXPECT_THROW(btcore::VarianceState(1, Estimator::sample), btcore::InvalidArgument);
  EXPECT_NO_THROW(btcore::VarianceState(1, Estimator::population));
}

}  // namespace
