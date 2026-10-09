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

/// Whether a variance divides the squared deviations by the number of values or by one less.
enum class Estimator { population, sample };

/// Variance of the last `period` values. The first `period - 1` outputs are missing, and so is
/// every output whose window holds a missing value. Each window is computed afresh from deviations
/// from its newest value, so a window of equal values gives exactly 0. A sample variance needs a
/// period of at least 2.
void variance(std::span<const double> values, int period, Estimator estimator,
              std::span<double> out);

void variance(const SeriesBatch& values, int period, Estimator estimator, std::span<double> out,
              unsigned threads);

/// The variance one value at a time, equal bit for bit to the batch form.
class VarianceState {
 public:
  VarianceState(int period, Estimator estimator);

  [[nodiscard]] double update(double value);

 private:
  // Each value is written twice, a period apart, so the last `period` values sit side by side.
  std::vector<double> window_;
  std::size_t period_;
  double divisor_;
  std::size_t next_ = 0;
  std::size_t seen_ = 0;
  std::size_t missing_ = 0;
};

/// The two lines of a price band on one bar.
struct Band {
  double upper;
  double lower;
};

/// Bollinger bands: the simple moving average plus and minus `width` population standard
/// deviations of the same `period` values. The first `period - 1` outputs are missing, and so is
/// every output whose window holds a missing value. A window of equal values puts both lines on the
/// average. `width` is finite and not negative.
void bollinger_bands(std::span<const double> values, int period, double width,
                     std::span<double> upper, std::span<double> lower);

void bollinger_bands(const SeriesBatch& values, int period, double width, std::span<double> upper,
                     std::span<double> lower, unsigned threads);

/// Bollinger bands one value at a time, equal bit for bit to the batch form.
class BollingerState {
 public:
  BollingerState(int period, double width);

  [[nodiscard]] Band update(double value);

 private:
  SmaState average_;
  VarianceState variance_;
  double width_;
};

/// The fractional return over `bars` values ending `skip` values back, computed as
/// (later - earlier) / earlier: nearby prices subtract exactly, so a small return keeps its
/// precision. The first `bars + skip` outputs are missing, and so is every output where either
/// value is missing. A return over 231 bars skipping 21 is the 12-1 momentum.
void simple_return(std::span<const double> values, int bars, int skip, std::span<double> out);

void simple_return(const SeriesBatch& values, int bars, int skip, std::span<double> out,
                   unsigned threads);

/// The value a fixed number of values back, one value at a time.
class Lookback {
 public:
  explicit Lookback(std::size_t distance);

  /// Records `value` and returns the value `distance` before it, missing until there is one.
  [[nodiscard]] double push(double value);

 private:
  std::vector<double> values_;
  std::size_t next_ = 0;
};

/// The fractional return one value at a time, equal bit for bit to the batch form.
class ReturnState {
 public:
  ReturnState(int bars, int skip);

  [[nodiscard]] double update(double value);

 private:
  Lookback later_;
  Lookback earlier_;
};

}  // namespace btcore
