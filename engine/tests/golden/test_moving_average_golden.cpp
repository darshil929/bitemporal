#include <gtest/gtest.h>

#include <btcore/indicators.hpp>
#include <string>

#include "golden_checks.hpp"

namespace {

using btcore::testing::expect_matches_golden;

TEST(MovingAverageGolden, SmaMatchesTheReference) {
  for (const int period : {20, 50, 200}) {
    expect_matches_golden("golden_moving_averages.csv", "sma_" + std::to_string(period),
                          [&](const auto& batch, auto out) { btcore::sma(batch, period, out, 0); });
  }
}

TEST(MovingAverageGolden, EmaMatchesTheReference) {
  for (const int period : {20, 50}) {
    expect_matches_golden("golden_moving_averages.csv", "ema_" + std::to_string(period),
                          [&](const auto& batch, auto out) { btcore::ema(batch, period, out, 0); });
  }
}

}  // namespace
