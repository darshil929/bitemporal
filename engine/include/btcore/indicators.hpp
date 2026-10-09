#pragma once

#include <btcore/types.hpp>
#include <cstddef>
#include <span>
#include <vector>

namespace btcore {

/// Simple moving average: the mean of the last `period` values. The first `period - 1` outputs are
/// missing, and so is every output whose window holds a missing value. The running sum is
/// compensated, so a long series accumulates no rounding drift.
void sma(std::span<const double> values, int period, std::span<double> out);

/// The batch form over every series of `values`, spread over `threads` threads (0: all hardware).
void sma(const SeriesBatch& values, int period, std::span<double> out, unsigned threads);

/// The simple moving average one value at a time, equal bit for bit to the batch form.
class SmaState {
 public:
  explicit SmaState(int period);

  [[nodiscard]] double update(double value);

 private:
  std::vector<double> window_;
  std::size_t next_ = 0;
  std::size_t seen_ = 0;
  std::size_t missing_ = 0;
  double total_ = 0.0;
  double compensation_ = 0.0;
};

/// Exponential moving average with k = 2 / (period + 1), seeded with the simple average of its
/// first `period` values and updated as k * value + (1 - k) * previous, as TA-Lib 0.8.1 computes
/// it. The first `period - 1` outputs are missing; a missing value yields a missing output and the
/// average is seeded again from the values after it.
void ema(std::span<const double> values, int period, std::span<double> out);

void ema(const SeriesBatch& values, int period, std::span<double> out, unsigned threads);

/// The exponential moving average one value at a time, equal bit for bit to the batch form.
class EmaState {
 public:
  explicit EmaState(int period);

  [[nodiscard]] double update(double value);

 private:
  int period_;
  double k_;
  int seeded_ = 0;
  double seed_total_ = 0.0;
  double average_ = 0.0;
};

/// Relative strength index, 100 * gain / (gain + loss) over Wilder's averages of the gains and
/// losses between successive values. Each average is seeded with the mean of the first `period`
/// changes, then updated as (average * (period - 1) + change) / period with the division taken as a
/// multiplication by 1 / period, in TA-Lib 0.8.1's order. The first `period` outputs are missing.
/// Where TA-Lib gives 0 for a series unchanged since its first value, the output stays missing
/// until the series moves. A missing value yields a missing output, and the warm-up starts again
/// after it.
void rsi(std::span<const double> values, int period, std::span<double> out);

void rsi(const SeriesBatch& values, int period, std::span<double> out, unsigned threads);

/// The relative strength index one value at a time, equal bit for bit to the batch form.
class RsiState {
 public:
  explicit RsiState(int period);

  [[nodiscard]] double update(double value);

 private:
  int period_;
  double inverse_period_;
  bool has_previous_ = false;
  double previous_ = 0.0;
  int changes_ = 0;
  double gain_ = 0.0;
  double loss_ = 0.0;
};

}  // namespace btcore
