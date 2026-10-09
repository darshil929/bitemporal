#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <limits>
#include <vector>

namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

std::vector<double> obv(const std::vector<double>& closes, const std::vector<double>& volumes) {
  std::vector<double> out(closes.size());
  btcore::on_balance_volume(closes, volumes, out);
  return out;
}

// From 100: up adds 50, unchanged holds, down subtracts 70, up adds 20.
TEST(OnBalanceVolume, AddsOnARiseSubtractsOnAFallAndHoldsOtherwise) {
  EXPECT_EQ(obv({10, 11, 11, 9, 12}, {100, 50, 60, 70, 20}),
            (std::vector<double>{100, 150, 150, 80, 100}));
}

// After the missing close the total starts again from the volume of the next bar.
TEST(OnBalanceVolume, StartsAgainAfterAMissingCloseOrVolume) {
  const auto out = obv({10, kNaN, 12, 13, 14}, {100, 40, 30, 20, kNaN});
  EXPECT_EQ(out[0], 100);
  EXPECT_TRUE(std::isnan(out[1]));
  EXPECT_EQ(out[2], 30);
  EXPECT_EQ(out[3], 50);
  EXPECT_TRUE(std::isnan(out[4]));
}

TEST(OnBalanceVolume, RefusesVolumesOrAnOutputOfAnotherLength) {
  std::vector<double> closes{1, 2, 3};
  std::vector<double> short_series(2);
  std::vector<double> out(3);
  EXPECT_THROW(btcore::on_balance_volume(closes, short_series, out), btcore::InvalidArgument);
  EXPECT_THROW(btcore::on_balance_volume(closes, closes, short_series), btcore::InvalidArgument);
}

}  // namespace
