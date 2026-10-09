#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <span>
#include <vector>

#include "form_checks.hpp"

namespace {

TEST(TradedValueProperties, BatchEqualsStreaming) {
  btcore::testing::expect_batch_equals_streaming<btcore::PriorMeanRatioState>(
      [](std::span<const double> v, int p, std::span<double> o) {
        btcore::ratio_to_prior_mean(v, p, o);
      },
      [](int period) { return period; });
}

// An unchanging volume stands at its own mean.
TEST(TradedValueProperties, AnUnchangingValueHasARatioOfOne) {
  for (const double level : {3.0, 1'250.0, 48'213'977.0}) {
    std::vector<double> out(40);
    btcore::ratio_to_prior_mean(std::vector<double>(40, level), 20, out);
    for (std::size_t index = 20; index < out.size(); ++index) {
      ASSERT_NEAR(out[index], 1.0, 1e-15) << level << " at " << index;
    }
  }
}

TEST(TradedValueProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) {
        btcore::ratio_to_prior_mean(batch, 20, out, threads);
      },
      [](auto values, auto out) { btcore::ratio_to_prior_mean(values, 20, out); });
}

}  // namespace
