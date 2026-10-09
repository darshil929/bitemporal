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

/// The value less the value `bars` before it. The first `bars` outputs are missing, and so is every
/// output where either value is missing.
void change(std::span<const double> values, int bars, std::span<double> out);

void change(const SeriesBatch& values, int bars, std::span<double> out, unsigned threads);

/// The change one value at a time, equal bit for bit to the batch form.
class ChangeState {
 public:
  explicit ChangeState(int bars);

  [[nodiscard]] double update(double value);

 private:
  Lookback earlier_;
};

/// Realised volatility: the sample standard deviation of the last `period` daily log returns, each
/// `log1p` of the fractional return from one value to the next, times the square root of
/// `periods_per_year`. The first `period` outputs are missing, and so is every output whose window
/// holds a missing return. `period` is at least 2 and `periods_per_year` at least 1.
void realised_volatility(std::span<const double> values, int period, int periods_per_year,
                         std::span<double> out);

void realised_volatility(const SeriesBatch& values, int period, int periods_per_year,
                         std::span<double> out, unsigned threads);

/// Realised volatility one value at a time, equal bit for bit to the batch form.
class VolatilityState {
 public:
  VolatilityState(int period, int periods_per_year);

  [[nodiscard]] double update(double value);

 private:
  ReturnState daily_;
  VarianceState variance_;
  double annualiser_;
};

/// Which end of a window a rolling extreme keeps.
enum class Extreme { maximum, minimum };

/// The largest or smallest of the last `period` values. The first `period - 1` outputs are missing,
/// and so is every output whose window holds a missing value. A queue holds only the values that
/// could still become the extreme, so each value costs constant time on average.
void rolling_extreme(std::span<const double> values, int period, Extreme extreme,
                     std::span<double> out);

void rolling_extreme(const SeriesBatch& values, int period, Extreme extreme, std::span<double> out,
                     unsigned threads);

/// The rolling extreme one value at a time, equal bit for bit to the batch form.
class RollingExtremeState {
 public:
  RollingExtremeState(int period, Extreme extreme);

  [[nodiscard]] double update(double value);

 private:
  [[nodiscard]] bool keeps(double held, double arriving) const;
  [[nodiscard]] std::size_t wrapped(std::size_t index) const;

  // The queue's values and their positions, oldest first from `head_`, in rings of `period`.
  std::vector<double> held_;
  std::vector<std::size_t> held_at_;
  std::vector<unsigned char> was_missing_;
  std::size_t period_;
  Extreme extreme_;
  std::size_t head_ = 0;
  std::size_t size_ = 0;
  std::size_t slot_ = 0;
  std::size_t seen_ = 0;
  std::size_t missing_ = 0;
};

/// The fractional distance of each value from the highest of the last `period` highs, the day's own
/// among them: (value - highest) / highest, 0 on the day of a new high. The first `period - 1`
/// outputs are missing, and so is every output where the value or a high in the window is missing.
void distance_from_high(std::span<const double> values, std::span<const double> highs, int period,
                        std::span<double> out);

/// The batch form over every series of `values`, with `highs` laid out like them.
void distance_from_high(const SeriesBatch& values, std::span<const double> highs, int period,
                        std::span<double> out, unsigned threads);

/// 1 where a value is the extreme of the last `period` values, at or beyond every one of the
/// `period - 1` before it, and 0 where it is not. The first `period - 1` outputs are missing, and
/// so is every output whose window holds a missing value.
void new_extreme(std::span<const double> values, int period, Extreme extreme,
                 std::span<double> out);

void new_extreme(const SeriesBatch& values, int period, Extreme extreme, std::span<double> out,
                 unsigned threads);

/// The distance from the high one value at a time, equal bit for bit to the batch form.
class HighDistanceState {
 public:
  explicit HighDistanceState(int period);

  [[nodiscard]] double update(double value, double high);

 private:
  RollingExtremeState highest_;
};

/// The new extreme flag one value at a time, equal bit for bit to the batch form.
class NewExtremeState {
 public:
  NewExtremeState(int period, Extreme extreme);

  [[nodiscard]] double update(double value);

 private:
  RollingExtremeState extreme_;
};

/// Each value over the mean of the `period` values before it. The first `period` outputs are
/// missing, and so is every output where the value or one of those before it is missing.
void ratio_to_prior_mean(std::span<const double> values, int period, std::span<double> out);

void ratio_to_prior_mean(const SeriesBatch& values, int period, std::span<double> out,
                         unsigned threads);

/// The ratio to the prior mean one value at a time, equal bit for bit to the batch form.
class PriorMeanRatioState {
 public:
  explicit PriorMeanRatioState(int period);

  [[nodiscard]] double update(double value);

 private:
  SmaState mean_;
  double prior_mean_ = missing;
};

/// A part as a percentage of its whole, part / whole * 100; missing where either is missing.
[[nodiscard]] inline double percentage(double part, double whole) { return part / whole * 100.0; }

/// `percentage` value by value. It reads no window, so one call covers any number of series laid
/// end to end.
void percentage_of(std::span<const double> parts, std::span<const double> wholes,
                   std::span<double> out);

}  // namespace btcore
