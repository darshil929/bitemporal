#include <gtest/gtest.h>

#include <algorithm>
#include <btcore/features.hpp>
#include <cmath>
#include <cstddef>
#include <string>
#include <vector>

namespace {

using btcore::Feature;

// Closes rising by one from 100.
std::vector<double> rising(std::size_t length) {
  std::vector<double> values(length);
  for (std::size_t index = 0; index < length; ++index) {
    values[index] = 100.0 + static_cast<double>(index);
  }
  return values;
}

std::vector<double> computed(const std::vector<double>& values, const std::vector<double>& factor) {
  std::vector<double> out(values.size() * btcore::feature_count);
  btcore::daily_features({values, factor}, out);
  return out;
}

double at(const std::vector<double>& out, std::size_t length, Feature feature, std::size_t bar) {
  return out[static_cast<std::size_t>(feature) * length + bar];
}

TEST(DailyFeatures, LeavesTheLeadingBlanksEachColumnStates) {
  constexpr std::size_t kLength = 300;
  const auto out = computed(rising(kLength), std::vector<double>(kLength, 1.0));
  for (std::size_t feature = 0; feature < btcore::feature_count; ++feature) {
    SCOPED_TRACE(std::string(btcore::feature_columns[feature].name));
    const auto blanks = static_cast<std::size_t>(btcore::feature_columns[feature].leading_blanks);
    for (std::size_t bar = 0; bar < kLength; ++bar) {
      ASSERT_EQ(std::isnan(out[feature * kLength + bar]), bar < blanks) << "bar " << bar;
    }
  }
}

// The close of bar 299 is 399, and each window reads the close its length before.
TEST(DailyFeatures, ReadsEachReturnOverItsOwnLength) {
  constexpr std::size_t kLength = 300;
  const auto out = computed(rising(kLength), std::vector<double>(kLength, 1.0));
  EXPECT_EQ(at(out, kLength, Feature::return_1w, 299), (399.0 - 394.0) / 394.0);
  EXPECT_EQ(at(out, kLength, Feature::return_1m, 299), (399.0 - 378.0) / 378.0);
  EXPECT_EQ(at(out, kLength, Feature::return_3m, 299), (399.0 - 336.0) / 336.0);
  EXPECT_EQ(at(out, kLength, Feature::return_6m, 299), (399.0 - 273.0) / 273.0);
  EXPECT_EQ(at(out, kLength, Feature::return_1y, 299), (399.0 - 147.0) / 147.0);
  EXPECT_EQ(at(out, kLength, Feature::momentum_12_1, 299), (378.0 - 147.0) / 147.0);
}

// Adjusted closes 100 to 124 under a factor of 0.5 through bar 21 and 1 after it. The 20-bar
// averages at bar 19 are 109.5 adjusted and 219 in the day's scale; at bar 24, 114.5 in both.
TEST(DailyFeatures, ReadsEachLevelInItsOwnDaysScale) {
  constexpr std::size_t kLength = 25;
  std::vector<double> factor(kLength, 1.0);
  std::fill(factor.begin(), factor.begin() + 22, 0.5);
  const auto out = computed(rising(kLength), factor);
  EXPECT_EQ(at(out, kLength, Feature::change_1d, 5), 2.0);
  EXPECT_EQ(at(out, kLength, Feature::change_1d, 23), 1.0);
  EXPECT_EQ(at(out, kLength, Feature::sma_20, 19), 219.0);
  EXPECT_EQ(at(out, kLength, Feature::ema_20, 19), 219.0);
  EXPECT_EQ(at(out, kLength, Feature::sma_20, 24), 114.5);
  EXPECT_EQ(at(out, kLength, Feature::return_1d, 5), (105.0 - 104.0) / 104.0);
}

TEST(DailyFeatures, RefusesInputsAndOutputsOfAnotherLength) {
  const auto values = rising(30);
  const std::vector<double> factor(30, 1.0);
  const std::vector<double> short_factor(29, 1.0);
  std::vector<double> out(30 * btcore::feature_count);
  EXPECT_THROW(btcore::daily_features({values, short_factor}, out), btcore::InvalidArgument);
  out.pop_back();
  EXPECT_THROW(btcore::daily_features({values, factor}, out), btcore::InvalidArgument);
}

}  // namespace
