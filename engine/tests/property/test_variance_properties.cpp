#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <cmath>
#include <cstddef>
#include <span>
#include <string>
#include <vector>

#include "form_checks.hpp"
#include "series_generators.hpp"

namespace {

using btcore::Estimator;
using btcore::testing::expect_batch_equals_streaming;
using btcore::testing::SeriesCase;

struct PopulationVarianceState : btcore::VarianceState {
  explicit PopulationVarianceState(int period) : VarianceState(period, Estimator::population) {}
};

struct SampleVarianceState : btcore::VarianceState {
  explicit SampleVarianceState(int period) : VarianceState(period, Estimator::sample) {}
};

constexpr int kSamplePeriods[] = {2, 14, 20};
constexpr auto kWindowBlanks = [](int period) { return period - 1; };

// Neumaier-compensated sums in two passes: a reference accurate to about the last bit.
double reference_variance(std::span<const double> window) {
  const auto compensated = [&](auto term) {
    double total = 0.0;
    double compensation = 0.0;
    for (const double value : window) {
      const double addend = term(value);
      const double sum = total + addend;
      compensation +=
          std::fabs(total) >= std::fabs(addend) ? (total - sum) + addend : (addend - sum) + total;
      total = sum;
    }
    return total + compensation;
  };
  const auto size = static_cast<double>(window.size());
  const double mean = compensated([](double value) { return value; }) / size;
  return compensated([mean](double value) { return (value - mean) * (value - mean); }) / size;
}

TEST(VarianceProperties, BatchEqualsStreaming) {
  expect_batch_equals_streaming<PopulationVarianceState>(
      [](std::span<const double> v, int p, std::span<double> o) {
        btcore::variance(v, p, Estimator::population, o);
      },
      kWindowBlanks);
  expect_batch_equals_streaming<SampleVarianceState>(
      [](std::span<const double> v, int p, std::span<double> o) {
        btcore::variance(v, p, Estimator::sample, o);
      },
      kWindowBlanks, kSamplePeriods);
}

TEST(VarianceProperties, AWindowIsNeverNegativeAndMatchesTwoCompensatedPasses) {
  const auto seed = btcore::testing::property_seed();
  for (const SeriesCase& series : btcore::testing::window_cases(20, seed)) {
    SCOPED_TRACE("seed " + std::to_string(seed) + ", " + series.label);
    std::vector<double> out(series.values.size());
    btcore::variance(series.values, 20, Estimator::population, out);
    for (std::size_t index = 0; index < out.size(); ++index) {
      if (std::isnan(out[index])) {
        continue;
      }
      const double expected =
          reference_variance(std::span<const double>(series.values).subspan(index - 19, 20));
      ASSERT_GE(out[index], 0.0) << "index " << index;
      ASSERT_NEAR(out[index], expected, 1e-14 * expected) << "index " << index;
    }
  }
}

TEST(VarianceProperties, TheUniverseFormMatchesEachSeriesOnAnyThreadCount) {
  btcore::testing::expect_universe_matches_each_series(
      [](const auto& batch, auto out, unsigned threads) {
        btcore::variance(batch, 20, Estimator::sample, out, threads);
      },
      [](auto values, auto out) { btcore::variance(values, 20, Estimator::sample, out); });
}

}  // namespace
