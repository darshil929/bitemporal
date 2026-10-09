#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::testing::expect_batch_equals_streaming;

constexpr auto kLeadingBars = [](int bars) { return bars; };

template <int skip>
struct SkippingReturnState : btcore::ReturnState {
  explicit SkippingReturnState(int bars) : ReturnState(bars, skip) {}
};

TEST(ReturnsProperties, BatchEqualsStreaming) {
  expect_batch_equals_streaming<SkippingReturnState<0>>(
      [](std::span<const double> v, int b, std::span<double> o) {
        btcore::simple_return(v, b, 0, o);
      },
      kLeadingBars);
  expect_batch_equals_streaming<SkippingReturnState<3>>(
      [](std::span<const double> v, int b, std::span<double> o) {
        btcore::simple_return(v, b, 3, o);
      },
      [](int bars) { return bars + 3; });
}

// One-bar returns compound to the return over the whole stretch.
TEST(ReturnsProperties, DailyReturnsCompoundToTheLongerReturn) {
  const auto seed = btcore::testing::property_seed();
  const auto drawn = btcore::testing::universe(20, 300, seed);
  const btcore::SeriesBatch batch(drawn.values, drawn.offsets);
  for (std::size_t index = 0; index < batch.size(); ++index) {
    const auto values = batch.series(index);
    std::vector<double> daily(values.size());
    std::vector<double> monthly(values.size());
    btcore::simple_return(values, 1, 0, daily);
    btcore::simple_return(values, 21, 0, monthly);
    for (std::size_t end = 21; end < values.size(); ++end) {
      double growth = 1.0;
      for (std::size_t day = end - 20; day <= end; ++day) {
        growth *= 1.0 + daily[day];
      }
      ASSERT_NEAR(growth - 1.0, monthly[end], 1e-13)
          << "seed " << seed << ", series " << index << ", bar " << end;
    }
  }
}

TEST(ReturnsProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) {
        btcore::simple_return(batch, 21, 5, out, threads);
      },
      [](auto values, auto out) { btcore::simple_return(values, 21, 5, out); });
}

}  // namespace
