#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <cmath>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::testing::SeriesCase;

TEST(VolumeFlowProperties, BatchEqualsStreamingAndStaysWithinTheVolumeTraded) {
  const auto seed = btcore::testing::property_seed();
  for (const SeriesCase& series : btcore::testing::window_cases(20, seed)) {
    SCOPED_TRACE("seed " + std::to_string(seed) + ", " + series.label);
    std::vector<double> volumes(series.values.size());
    for (std::size_t index = 0; index < volumes.size(); ++index) {
      volumes[index] = 1'000.0 + 37.0 * static_cast<double>(index % 11);
    }
    std::vector<double> out(series.values.size());
    btcore::on_balance_volume(series.values, volumes, out);
    btcore::OnBalanceVolumeState state;
    std::vector<double> streamed;
    double traded = 0.0;
    for (std::size_t index = 0; index < volumes.size(); ++index) {
      streamed.push_back(state.update(series.values[index], volumes[index]));
      traded = std::isnan(series.values[index]) ? 0.0 : traded + volumes[index];
      if (!std::isnan(out[index])) {
        ASSERT_LE(std::fabs(out[index]), traded) << "index " << index;
      }
    }
    btcore::testing::expect_identical(out, streamed);
  }
}

TEST(VolumeFlowProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) {
        btcore::on_balance_volume(batch, batch.values(), out, threads);
      },
      [](auto values, auto out) { btcore::on_balance_volume(values, values, out); });
}

}  // namespace
