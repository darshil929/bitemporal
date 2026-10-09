#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <btcore/maths.hpp>
#include <cmath>
#include <limits>
#include <vector>

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

std::vector<double> volatility(const std::vector<double>& values, int period) {
  std::vector<double> out(values.size());
  btcore::realised_volatility(values, period, 252, out);
  return out;
}

// Returns +0.1 and -0.1 between 100, 110 and 99: their log returns a and b have a sample variance
// of (a - b)^2 / 2 over two.
TEST(RealisedVolatility, AnnualisesTheSampleDeviationOfLogReturns) {
  const auto out = volatility({100, 110, 99}, 2);
  const double a = btcore::log1p(0.1);
  const double b = btcore::log1p(-0.1);
  EXPECT_TRUE(std::isnan(out[0]) && std::isnan(out[1]));
  EXPECT_DOUBLE_EQ(out[2], std::sqrt((a - b) * (a - b) / 2) * std::sqrt(252.0));
}

TEST(RealisedVolatility, GivesZeroOnUnchangedValuesAndMissingAcrossAGap) {
  EXPECT_EQ(volatility({7.5, 7.5, 7.5, 7.5}, 3)[3], 0.0);
  const auto gapped = volatility({100, 101, kNaN, 103, 104, 105, 106}, 2);
  for (const std::size_t index : {2U, 3U, 4U}) {
    EXPECT_TRUE(std::isnan(gapped[index])) << "index " << index;
  }
  EXPECT_FALSE(std::isnan(gapped[5]));
}

TEST(RealisedVolatility, RefusesAShortPeriodAndANonPositiveYear) {
  std::vector<double> values{1, 2, 3};
  EXPECT_THROW(btcore::realised_volatility(values, 1, 252, values), btcore::InvalidArgument);
  EXPECT_THROW(btcore::realised_volatility(values, 2, 0, values), btcore::InvalidArgument);
  EXPECT_THROW(btcore::VolatilityState(1, 252), btcore::InvalidArgument);
}

}  // namespace
