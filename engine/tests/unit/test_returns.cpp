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

std::vector<double> simple_return(const std::vector<double>& values, int bars, int skip) {
  std::vector<double> out(values.size());
  btcore::simple_return(values, bars, skip, out);
  return out;
}

// 100 to 110 is 0.1, 110 to 99 is -0.1, 99 to 99 is 0; two bars from 100 to 99 is -0.01.
TEST(SimpleReturn, DividesTheChangeByTheEarlierValue) {
  const std::vector<double> values{100, 110, 99, 99};
  expect_series(simple_return(values, 1, 0), {missing, 0.1, -0.1, 0});
  expect_series(simple_return(values, 2, 0), {missing, missing, -0.01, -0.1});
}

// Skipping one value, each output is the previous bar's return.
TEST(SimpleReturn, EndsSkipValuesBack) {
  expect_series(simple_return({100, 110, 99, 99}, 1, 1), {missing, missing, 0.1, -0.1});
}

TEST(SimpleReturn, LeavesAReturnWithAMissingEndMissing) {
  expect_series(simple_return({100, kNaN, 120, 132}, 1, 0), {missing, missing, missing, 0.1});
  expect_series(simple_return({100, 110}, 3, 0), {missing, missing});
}

TEST(SimpleReturn, RefusesABarCountBelowOneANegativeSkipAndAMismatchedOutput) {
  std::vector<double> values{1, 2, 3};
  std::vector<double> short_out(2);
  EXPECT_THROW(btcore::simple_return(values, 0, 0, values), btcore::InvalidArgument);
  EXPECT_THROW(btcore::simple_return(values, 1, -1, values), btcore::InvalidArgument);
  EXPECT_THROW(btcore::simple_return(values, 1, 0, short_out), btcore::InvalidArgument);
  EXPECT_THROW(btcore::ReturnState(1, -2), btcore::InvalidArgument);
}

}  // namespace
