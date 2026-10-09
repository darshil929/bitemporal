#pragma once

namespace btcore {

/// The natural logarithm of 1 + x, within one unit in the last place, computed from basic
/// arithmetic alone so that every platform returns the same bits; the maths libraries of macOS and
/// Linux differ in the last bit on some inputs. -1 gives negative infinity, and a value below -1 or
/// NaN gives NaN.
[[nodiscard]] double log1p(double x);

}  // namespace btcore
