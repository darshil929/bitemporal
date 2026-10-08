#include <gtest/gtest.h>

#include <cmath>

namespace {

// Volatile operands keep the compiler from evaluating the expressions while building, where its own
// arithmetic would stand in for the code it emits.
volatile double just_above_one = 1.0 + 0x1p-30;
volatile double just_below_one = 1.0 - 0x1p-30;
volatile double minus_one = -1.0;

}  // namespace

// The exact product is 1 - 2^-60, which rounds to 1. Rounded before the addition, the sum is 0;
// fused into one rounding with the addition, it is -2^-60.
TEST(Arithmetic, MultiplyThenAddRoundsEachStep) {
  const double a = just_above_one;
  const double b = just_below_one;
  const double c = minus_one;
  EXPECT_EQ(a * b + c, 0.0);
}

TEST(Arithmetic, ExplicitFusedMultiplyAddRoundsOnce) {
  const double a = just_above_one;
  const double b = just_below_one;
  const double c = minus_one;
  EXPECT_EQ(std::fma(a, b, c), -0x1p-60);
}
