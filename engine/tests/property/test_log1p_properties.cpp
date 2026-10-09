#include <gtest/gtest.h>

#include <btcore/maths.hpp>
#include <cmath>
#include <limits>

#include "series_generators.hpp"

namespace {

constexpr int kDraws = 200'000;

// Both this logarithm and the platform's lie within about half a unit of the exact value, so they
// differ by at most one unit in the last place.
void expect_within_a_unit(double x, std::uint64_t seed) {
  const double ours = btcore::log1p(x);
  const double theirs = std::log1p(x);
  const double unit = std::nextafter(std::fabs(theirs), std::numeric_limits<double>::infinity()) -
                      std::fabs(theirs);
  ASSERT_LE(std::fabs(ours - theirs), unit) << "seed " << seed << ", x " << std::hexfloat << x;
}

TEST(Log1pProperties, StaysWithinAUnitOfThePlatformLogarithm) {
  const auto seed = btcore::testing::property_seed();
  btcore::testing::SeriesGenerator draw(seed);
  for (int index = 0; index < kDraws; ++index) {
    const double unit = draw.uniform();
    expect_within_a_unit(0.4 * unit - 0.2, seed);
    expect_within_a_unit(-unit, seed);
    expect_within_a_unit(std::ldexp(unit, (index % 80) - 50), seed);
  }
}

}  // namespace
