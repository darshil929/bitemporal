#include <gtest/gtest.h>

#include <atomic>
#include <btcore/parallel.hpp>
#include <btcore/types.hpp>
#include <cstddef>
#include <vector>

namespace {

std::vector<double> squares(std::size_t count, unsigned threads) {
  std::vector<double> output(count, 0.0);
  btcore::parallel_for(count, threads, [&](std::size_t index) {
    const auto value = static_cast<double>(index);
    output[index] = value * value;
  });
  return output;
}

TEST(ParallelFor, CallsNothingForNoIndices) {
  std::atomic<int> calls{0};
  btcore::parallel_for(0, 4, [&](std::size_t) { calls.fetch_add(1); });
  EXPECT_EQ(calls.load(), 0);
}

TEST(ParallelFor, VisitsEveryIndexExactlyOnce) {
  constexpr std::size_t kCount = 10'000;
  std::vector<std::atomic<int>> visits(kCount);
  btcore::parallel_for(kCount, 8, [&](std::size_t index) { visits[index].fetch_add(1); });
  for (std::size_t index = 0; index < kCount; ++index) {
    ASSERT_EQ(visits[index].load(), 1) << "index " << index;
  }
}

TEST(ParallelFor, GivesTheSameResultOnAnyNumberOfThreads) {
  constexpr std::size_t kCount = 6'000;
  const auto alone = squares(kCount, 1);
  EXPECT_EQ(squares(kCount, 2), alone);
  EXPECT_EQ(squares(kCount, 8), alone);
  EXPECT_EQ(squares(kCount, 0), alone);
}

TEST(ParallelFor, RaisesAWorkersExceptionOnTheCallingThread) {
  const auto fail_at_one_index = [](std::size_t index) {
    if (index == 4'321) {
      throw btcore::InvalidArgument("index 4321 refused");
    }
  };
  for (const unsigned threads : {1U, 2U, 8U}) {
    try {
      btcore::parallel_for(10'000, threads, fail_at_one_index);
      FAIL() << "no exception on " << threads << " threads";
    } catch (const btcore::InvalidArgument& error) {
      EXPECT_STREQ(error.what(), "index 4321 refused");
    }
  }
}

}  // namespace
