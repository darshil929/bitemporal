#include <gtest/gtest.h>

#include <btcore/types.hpp>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace {

using btcore::InvalidArgument;
using btcore::SeriesBatch;

TEST(Missing, IsNotANumber) {
  EXPECT_TRUE(btcore::is_missing(btcore::missing));
  EXPECT_FALSE(btcore::is_missing(0.0));
}

TEST(InvalidArgument, IsAStandardInvalidArgument) {
  EXPECT_THROW(throw InvalidArgument("refused"), std::invalid_argument);
}

TEST(RequirePeriod, RefusesAWindowShorterThanOneBar) {
  EXPECT_THROW(btcore::require_period(0), InvalidArgument);
  EXPECT_THROW(btcore::require_period(-5), InvalidArgument);
  EXPECT_NO_THROW(btcore::require_period(1));
}

TEST(RequireSameLength, RefusesAnOutputOfAnotherLength) {
  EXPECT_THROW(btcore::require_same_length(10, 9), InvalidArgument);
  EXPECT_NO_THROW(btcore::require_same_length(10, 10));
}

TEST(SeriesBatch, SplitsValuesAtTheOffsets) {
  const std::vector<double> values{1.0, 2.0, 3.0, 4.0, 5.0};
  const std::vector<std::int64_t> offsets{0, 3, 3, 5};
  const SeriesBatch batch(values, offsets);

  ASSERT_EQ(batch.size(), 3U);
  EXPECT_EQ(std::vector<double>(batch.series(0).begin(), batch.series(0).end()),
            (std::vector<double>{1.0, 2.0, 3.0}));
  EXPECT_TRUE(batch.series(1).empty());
  EXPECT_EQ(std::vector<double>(batch.series(2).begin(), batch.series(2).end()),
            (std::vector<double>{4.0, 5.0}));
}

TEST(SeriesBatch, GivesEachSeriesItsPartOfAnOutput) {
  const std::vector<double> values{1.0, 2.0, 3.0, 4.0, 5.0};
  const std::vector<std::int64_t> offsets{0, 3, 5};
  const SeriesBatch batch(values, offsets);
  std::vector<double> output(values.size(), 0.0);

  auto second = batch.series(output, 1);
  second[0] = 9.0;

  EXPECT_EQ(second.size(), 2U);
  EXPECT_EQ(output[3], 9.0);
  std::vector<double> short_output(4);
  EXPECT_THROW(static_cast<void>(batch.series(short_output, 0)), InvalidArgument);
}

TEST(SeriesBatch, HoldsNoSeriesWhenOffsetsHoldOnlyTheLeadingZero) {
  const std::vector<double> values;
  const std::vector<std::int64_t> offsets{0};
  EXPECT_EQ(SeriesBatch(values, offsets).size(), 0U);
}

TEST(SeriesBatch, RefusesOffsetsThatDoNotDescribeTheValues) {
  const std::vector<double> values{1.0, 2.0, 3.0};
  const std::vector<std::int64_t> none;
  const std::vector<std::int64_t> not_from_zero{1, 3};
  const std::vector<std::int64_t> decreasing{0, 2, 1, 3};
  const std::vector<std::int64_t> short_of_the_end{0, 2};
  const std::vector<std::int64_t> past_the_end{0, 4};

  EXPECT_THROW(SeriesBatch(values, none), InvalidArgument);
  EXPECT_THROW(SeriesBatch(values, not_from_zero), InvalidArgument);
  EXPECT_THROW(SeriesBatch(values, decreasing), InvalidArgument);
  EXPECT_THROW(SeriesBatch(values, short_of_the_end), InvalidArgument);
  EXPECT_THROW(SeriesBatch(values, past_the_end), InvalidArgument);
}

TEST(SeriesBatch, RefusesASeriesItDoesNotHold) {
  const std::vector<double> values{1.0, 2.0};
  const std::vector<std::int64_t> offsets{0, 2};
  const SeriesBatch batch(values, offsets);
  EXPECT_THROW(static_cast<void>(batch.series(1)), InvalidArgument);
}

}  // namespace
