#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <limits>
#include <utility>
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

std::pair<std::vector<double>, std::vector<double>> bands(const std::vector<double>& values,
                                                          int period, double width) {
  std::vector<double> upper(values.size());
  std::vector<double> lower(values.size());
  btcore::bollinger_bands(values, period, width, upper, lower);
  return {upper, lower};
}

// Averages 2, 3 and 13/3 with population variances 2/3, 2/3 and 14/9.
TEST(BollingerBands, PlacesTheLinesWidthDeviationsFromTheAverage) {
  const double near = 2 * std::sqrt(2.0 / 3);
  const double far = 2 * std::sqrt(14.0 / 9);
  const auto [upper, lower] = bands({1, 2, 3, 4, 6}, 3, 2.0);
  expect_series(upper, {missing, missing, 2 + near, 3 + near, 13.0 / 3 + far});
  expect_series(lower, {missing, missing, 2 - near, 3 - near, 13.0 / 3 - far});
}

// Each window holding the missing third value is missing; [4, 5] and [5, 6] deviate by 0.5.
TEST(BollingerBands, LeavesEveryWindowHoldingAMissingValueMissing) {
  const auto [upper, lower] = bands({1, 2, kNaN, 4, 5, 6}, 2, 2.0);
  expect_series(upper, {missing, 2.5, missing, missing, 5.5, 6.5});
  expect_series(lower, {missing, 0.5, missing, missing, 3.5, 4.5});
}

TEST(BollingerBands, CloseOnTheAverageOverEqualValuesOrAtWidthZero) {
  const auto [upper, lower] = bands({5, 7, 0.1, 0.1, 0.1}, 3, 2.0);
  EXPECT_EQ(upper[4], lower[4]);
  const auto [narrow_upper, narrow_lower] = bands({1, 2, 3, 4, 6}, 3, 0.0);
  for (std::size_t index = 2; index < narrow_upper.size(); ++index) {
    EXPECT_EQ(narrow_upper[index], narrow_lower[index]) << "index " << index;
  }
}

TEST(BollingerBands, RefusesANegativeOrUnboundedWidthAndAMismatchedOutput) {
  std::vector<double> values{1, 2, 3};
  std::vector<double> upper(3);
  std::vector<double> short_lower(2);
  EXPECT_THROW(btcore::bollinger_bands(values, 2, -1.0, upper, upper), btcore::InvalidArgument);
  EXPECT_THROW(btcore::bollinger_bands(values, 2, kNaN, upper, upper), btcore::InvalidArgument);
  EXPECT_THROW(btcore::bollinger_bands(values, 2, 2.0, upper, short_lower),
               btcore::InvalidArgument);
  EXPECT_THROW(btcore::BollingerState(2, std::numeric_limits<double>::infinity()),
               btcore::InvalidArgument);
}

}  // namespace
