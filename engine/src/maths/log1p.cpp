/*
 * ====================================================
 * Copyright (C) 1993 by Sun Microsystems, Inc. All rights reserved.
 *
 * Developed at SunPro, a Sun Microsystems, Inc. business.
 * Permission to use, copy, modify, and distribute this
 * software is freely granted, provided that this notice
 * is preserved.
 * ====================================================
 */

// FreeBSD's lib/msun/src/s_log1p.c, with the words of a double read and written through
// std::bit_cast. 1 + x is reduced to 2^k * (1 + f) with sqrt(2)/2 < 1 + f < sqrt(2); with
// s = f / (2 + f), log(1 + f) = f - (hfsq - s * (hfsq + R)), where hfsq = f * f / 2 and R is a
// degree-14 polynomial in s within 2^-58.45 of the series; the result is k * ln2 + log(1 + f), ln2
// split in two so k * ln2_hi is exact. When k is not 0, c / u corrects for rounding 1 + x to u.

#include <bit>
#include <btcore/maths.hpp>
#include <cstdint>
#include <limits>

namespace btcore {

namespace {

constexpr double kLn2High = 6.93147180369123816490e-01;  // 3fe62e42 fee00000
constexpr double kLn2Low = 1.90821492927058770002e-10;   // 3dea39ef 35793c76
constexpr double kLp1 = 6.666666666666735130e-01;        // 3FE55555 55555593
constexpr double kLp2 = 3.999999999940941908e-01;        // 3FD99999 9997FA04
constexpr double kLp3 = 2.857142874366239149e-01;        // 3FD24924 94229359
constexpr double kLp4 = 2.222219843214978396e-01;        // 3FCC71C5 1D8E78AF
constexpr double kLp5 = 1.818357216161805012e-01;        // 3FC74664 96CB03DE
constexpr double kLp6 = 1.531383769920937332e-01;        // 3FC39A09 D078C69F
constexpr double kLp7 = 1.479819860511658591e-01;        // 3FC2F112 DF3E5244

std::int32_t high_word(double x) {
  return static_cast<std::int32_t>(std::bit_cast<std::uint64_t>(x) >> 32);
}

double with_high_word(double x, std::int32_t high) {
  const std::uint64_t low = std::bit_cast<std::uint64_t>(x) & 0xffffffffU;
  return std::bit_cast<double>(
      (static_cast<std::uint64_t>(static_cast<std::uint32_t>(high)) << 32) | low);
}

}  // namespace

double log1p(double x) {
  const std::int32_t hx = high_word(x);
  const std::int32_t ax = hx & 0x7fffffff;
  std::int32_t k = 1;
  std::int32_t hu = 0;
  double f = 0.0;
  double c = 0.0;
  if (hx < 0x3fda827a) {     // 1 + x < sqrt(2)
    if (ax >= 0x3ff00000) {  // x <= -1
      return x == -1.0 ? -std::numeric_limits<double>::infinity()
                       : std::numeric_limits<double>::quiet_NaN();
    }
    if (ax < 0x3e200000) {  // |x| < 2^-29
      return ax < 0x3c900000 ? x : x - x * x * 0.5;
    }
    if (hx > 0 || hx <= static_cast<std::int32_t>(0xbfd2bec4U)) {  // sqrt(2)/2 <= 1 + x
      k = 0;
      f = x;
      hu = 1;
    }
  }
  if (hx >= 0x7ff00000) {  // infinity or NaN
    return x + x;
  }
  if (k != 0) {
    double u = x;
    if (hx < 0x43400000) {  // x < 2^53
      u = 1.0 + x;
      hu = high_word(u);
      k = (hu >> 20) - 1023;
      c = k > 0 ? 1.0 - (u - x) : x - (u - 1.0);
      c /= u;
    } else {
      hu = high_word(u);
      k = (hu >> 20) - 1023;
    }
    hu &= 0x000fffff;
    if (hu < 0x6a09e) {  // the mantissa of u is below sqrt(2)
      u = with_high_word(u, hu | 0x3ff00000);
    } else {
      k += 1;
      u = with_high_word(u, hu | 0x3fe00000);
      hu = (0x00100000 - hu) >> 2;
    }
    f = u - 1.0;
  }
  const double scale = k;
  const double hfsq = 0.5 * f * f;
  if (hu == 0) {  // |f| < 2^-20
    if (f == 0.0) {
      return k == 0 ? 0.0 : scale * kLn2High + (c + scale * kLn2Low);
    }
    const double r = hfsq * (1.0 - 0.66666666666666666 * f);
    return k == 0 ? f - r : scale * kLn2High - ((r - (scale * kLn2Low + c)) - f);
  }
  const double s = f / (2.0 + f);
  const double z = s * s;
  const double r =
      z * (kLp1 + z * (kLp2 + z * (kLp3 + z * (kLp4 + z * (kLp5 + z * (kLp6 + z * kLp7))))));
  return k == 0 ? f - (hfsq - s * (hfsq + r))
                : scale * kLn2High - ((hfsq - (s * (hfsq + r) + (scale * kLn2Low + c))) - f);
}

}  // namespace btcore
