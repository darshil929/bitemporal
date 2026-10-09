#include <gtest/gtest.h>

#include <bit>
#include <btcore/maths.hpp>
#include <cmath>
#include <cstdint>
#include <limits>

namespace {

struct Pinned {
  double input;
  double expected;
};

// The result for each input, bit for bit, on every platform. Each lies within 0.51 units in the
// last place of ln(1 + x) taken to 60 digits; the last two are daily returns of the golden series
// on which the macOS and Linux maths libraries disagree.
constexpr Pinned kPinned[] = {
    {0x0.0p+0, 0x0.0p+0},
    {-0x0.0p+0, -0x0.0p+0},
    {0x1.79ca10c924223p-67, 0x1.79ca10c924223p-67},
    {0x1.b7cdfd9d7bdbbp-34, 0x1.b7cdfd9d1d693p-34},
    {0x1.930be0ded288dp-7, 0x1.90967a5c9c8a0p-7},
    {-0x1.7f62b6ae7d567p-6, -0x1.83f143a794639p-6},
    {0x1.3333333333333p-2, 0x1.0ca937be1b9dcp-2},
    {-0x1.0000000000000p-2, -0x1.269621134db92p-2},
    {0x1.0000000000000p-1, 0x1.9f323ecbf984cp-2},
    {-0x1.0000000000000p-1, -0x1.62e42fefa39efp-1},
    {0x1.0000000000000p+0, 0x1.62e42fefa39efp-1},
    {0x1.8000000000000p+1, 0x1.62e42fefa39efp+0},
    {0x1.7e43c8800759cp+996, 0x1.5963447f87fb5p+9},
    {0x1.838db4de34816p-6, 0x1.7f0a78020bc70p-6},
    {0x1.285ac61e454bap-6, 0x1.25b4cbd915ce0p-6},
};

TEST(Log1p, ReturnsThePinnedBitsOnEveryPlatform) {
  for (const auto& [input, expected] : kPinned) {
    EXPECT_EQ(std::bit_cast<std::uint64_t>(btcore::log1p(input)),
              std::bit_cast<std::uint64_t>(expected))
        << std::hexfloat << input;
  }
}

TEST(Log1p, MeetsTheEdgesOfItsDomain) {
  constexpr double kInfinity = std::numeric_limits<double>::infinity();
  EXPECT_EQ(btcore::log1p(-1.0), -kInfinity);
  EXPECT_EQ(btcore::log1p(kInfinity), kInfinity);
  EXPECT_TRUE(std::isnan(btcore::log1p(-1.5)));
  EXPECT_TRUE(std::isnan(btcore::log1p(-kInfinity)));
  EXPECT_TRUE(std::isnan(btcore::log1p(std::numeric_limits<double>::quiet_NaN())));
}

}  // namespace
