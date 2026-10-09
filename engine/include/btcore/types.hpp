#pragma once

#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <span>
#include <stdexcept>

namespace btcore {

/// The value of an input that is absent, and of an output a window cannot fill.
inline constexpr double missing = std::numeric_limits<double>::quiet_NaN();

[[nodiscard]] inline bool is_missing(double value) noexcept { return std::isnan(value); }

/// A parameter or buffer a computation cannot accept.
class InvalidArgument : public std::invalid_argument {
 public:
  using std::invalid_argument::invalid_argument;
};

/// Throws InvalidArgument unless a window covers at least one bar.
void require_period(int period);

/// Throws InvalidArgument unless an output holds exactly as many values as its input.
void require_same_length(std::size_t input_length, std::size_t output_length);

/// Many series laid end to end, series i occupying values[offsets[i], offsets[i + 1]). The layout
/// is that of an Arrow list array; the batch borrows both arrays and owns neither.
class SeriesBatch {
 public:
  /// Throws InvalidArgument unless the offsets begin at 0, never decrease and end at the number of
  /// values.
  SeriesBatch(std::span<const double> values, std::span<const std::int64_t> offsets);

  /// The number of series.
  [[nodiscard]] std::size_t size() const noexcept { return offsets_.size() - 1; }

  [[nodiscard]] std::span<const double> values() const noexcept { return values_; }

  /// The values of series `index`.
  [[nodiscard]] std::span<const double> series(std::size_t index) const;

  /// The part of `output`, laid out like the values, that belongs to series `index`.
  [[nodiscard]] std::span<double> series(std::span<double> output, std::size_t index) const;

  /// The part of `input`, another array laid out like the values, that belongs to series `index`.
  [[nodiscard]] std::span<const double> input_series(std::span<const double> input,
                                                     std::size_t index) const;

  /// The part of `laid_out`, an array of any element laid out like the values, that belongs to
  /// series `index`.
  template <typename Element>
  [[nodiscard]] std::span<Element> slice(std::span<Element> laid_out, std::size_t index) const {
    require_same_length(values_.size(), laid_out.size());
    const std::size_t first = start(index);
    return laid_out.subspan(first, static_cast<std::size_t>(offsets_[index + 1]) - first);
  }

 private:
  [[nodiscard]] std::size_t start(std::size_t index) const;

  std::span<const double> values_;
  std::span<const std::int64_t> offsets_;
};

}  // namespace btcore
