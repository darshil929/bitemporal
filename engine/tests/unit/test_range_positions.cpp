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
      EXPECT_DOUBLE_EQ(actual[index], expected[index]) << "index " << index;
    }
  }
}

// Over two bars of highs 10, 12, 11 and 9 the highest are 12, 12 and 11: closes 12, 10.5 and 9 sit
// at 12, 1.5 below 12 and 2 below 11.
TEST(DistanceFromHigh, MeasuresTheCloseAgainstTheHighestHigh) {
  std::vector<double> out(4);
  btcore::distance_from_high(std::vector<double>{9, 12, 10.5, 9},
                             std::vector<double>{10, 12, 11, 9}, 2, out);
  expect_series(out, {missing, 0.0, -0.125, -2.0 / 11});
}

// Over two bars: 5 tops 3, 4 does not top 5, 6 tops 4; for lows, 4 is below 5 and 6 is not below 4.
TEST(NewExtreme, FlagsAValueAtOrBeyondTheWindowBeforeIt) {
  std::vector<double> highest(4);
  std::vector<double> lowest(4);
  btcore::new_extreme(std::vector<double>{3, 5, 4, 6}, 2, Extreme::maximum, highest);
  btcore::new_extreme(std::vector<double>{3, 5, 4, 6}, 2, Extreme::minimum, lowest);
  expect_series(highest, {missing, 1, 0, 1});
  expect_series(lowest, {missing, 0, 1, 0});
}

TEST(NewExtreme, CountsATieAsANewExtremeAndAMissingWindowAsMissing) {
  std::vector<double> out(5);
  btcore::new_extreme(std::vector<double>{4, 4, kNaN, 2, 3}, 2, Extreme::maximum, out);
  expect_series(out, {missing, 1, missing, missing, 1});
}

TEST(DistanceFromHigh, RefusesHighsOfAnotherLength) {
  std::vector<double> values{1, 2, 3};
  std::vector<double> highs{1, 2};
  std::vector<double> out(3);
  EXPECT_THROW(btcore::distance_from_high(values, highs, 2, out), btcore::InvalidArgument);
}

}  // namespace
