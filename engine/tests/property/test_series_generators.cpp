#include <gtest/gtest.h>

#include <algorithm>
#include <btcore/types.hpp>
#include <cmath>
#include <cstdlib>
#include <optional>
#include <string>

#include "series_generators.hpp"

namespace {

using btcore::testing::SeriesGenerator;

std::size_t missing_count(const std::vector<double>& values) {
  return static_cast<std::size_t>(
      std::count_if(values.begin(), values.end(), [](double value) { return std::isnan(value); }));
}

TEST(SeriesGenerator, DrawsTheSameSeriesFromTheSameSeed) {
  SeriesGenerator first(42);
  SeriesGenerator second(42);
  SeriesGenerator other(43);
  const auto walk = first.random_walk(500, 100.0);
  EXPECT_EQ(walk, second.random_walk(500, 100.0));
  EXPECT_NE(walk, other.random_walk(500, 100.0));
}

// The walk seed 7 draws, written out exactly; a platform drawing anything else cannot reproduce a
// failure reported with its seed.
TEST(SeriesGenerator, DrawsTheSameSeriesOnEveryPlatform) {
  SeriesGenerator generator(7);
  const auto walk = generator.random_walk(3, 100.0);
  ASSERT_EQ(walk.size(), 3U);
  EXPECT_EQ(walk[0], 100.0);
  EXPECT_EQ(walk[1], 0x1.97c1c2bca5ec5p+6);
  EXPECT_EQ(walk[2], 0x1.97635394ee7b9p+6);
}

TEST(SeriesGenerator, DrawsPricesInTheRangeSharesTradeIn) {
  SeriesGenerator generator(1);
  for (int draw = 0; draw < 10'000; ++draw) {
    const double price = generator.price();
    ASSERT_GE(price, 0.5);
    ASSERT_LT(price, 100'000.0);
  }
}

TEST(SeriesGenerator, WalksStartWhereAskedAndStayPositive) {
  SeriesGenerator generator(2);
  const auto walk = generator.random_walk(2'500, 3.25);
  EXPECT_EQ(walk.front(), 3.25);
  EXPECT_TRUE(std::all_of(walk.begin(), walk.end(), [](double close) { return close > 0.0; }));
}

TEST(SeriesGenerator, PunchesAsManyGapsAsAsked) {
  SeriesGenerator generator(3);
  auto walk = generator.random_walk(100, 50.0);
  generator.punch_gaps(walk, 7);
  EXPECT_EQ(missing_count(walk), 7U);
  generator.punch_gaps(walk, 1'000);
  EXPECT_EQ(missing_count(walk), 100U);
}

TEST(WindowCases, CoverEveryLengthAroundTheWindowAndTheEdgeShapes) {
  constexpr int kPeriod = 14;
  const auto cases = btcore::testing::window_cases(kPeriod, 4);
  for (std::size_t length = 0; length <= 3 * kPeriod + 5; ++length) {
    const auto label = "walk of " + std::to_string(length) + " bars";
    const auto found = std::find_if(cases.begin(), cases.end(),
                                    [&](const auto& series) { return series.label == label; });
    ASSERT_NE(found, cases.end()) << label;
    EXPECT_EQ(found->values.size(), length);
  }

  const auto by_label = [&](const std::string& label) {
    return std::find_if(cases.begin(), cases.end(),
                        [&](const auto& series) { return series.label == label; })
        ->values;
  };
  const auto flat = by_label("flat");
  EXPECT_TRUE(
      std::all_of(flat.begin(), flat.end(), [&](double close) { return close == flat[0]; }));
  const auto stalled = by_label("walk holding a flat stretch");
  EXPECT_TRUE(std::all_of(stalled.begin() + kPeriod - 1, stalled.begin() + 2 * kPeriod + 1,
                          [&](double close) { return close == stalled[kPeriod - 1]; }));
  EXPECT_EQ(missing_count(by_label("walk with 1 missing")), 1U);
  EXPECT_EQ(missing_count(by_label("walk with 3 missing")), 3U);
}

TEST(Universe, LaysSeriesEndToEndAsTheEngineTakesThem) {
  const auto universe = btcore::testing::universe(25, 40, 5);
  const btcore::SeriesBatch batch(universe.values, universe.offsets);
  ASSERT_EQ(batch.size(), 25U);
  for (std::size_t index = 0; index < batch.size(); ++index) {
    EXPECT_EQ(batch.series(index).size(), 40U);
  }
}

// A seed the run was started with is put back for the tests after this one.
TEST(PropertySeed, ReadsTheEnvironmentWhenSet) {
  const char* configured = std::getenv("BTCORE_PROPERTY_SEED");
  const std::optional<std::string> original =
      configured != nullptr ? std::optional<std::string>(configured) : std::nullopt;
  ASSERT_EQ(unsetenv("BTCORE_PROPERTY_SEED"), 0);
  const auto fixed = btcore::testing::property_seed();
  ASSERT_EQ(setenv("BTCORE_PROPERTY_SEED", "123456789", 1), 0);
  EXPECT_EQ(btcore::testing::property_seed(), 123456789U);
  ASSERT_EQ(unsetenv("BTCORE_PROPERTY_SEED"), 0);
  EXPECT_EQ(btcore::testing::property_seed(), fixed);
  if (original) {
    ASSERT_EQ(setenv("BTCORE_PROPERTY_SEED", original->c_str(), 1), 0);
  }
}

}  // namespace
