#include <btcore/indicators.hpp>
#include <string>

#include "series_forms.hpp"

namespace btcore {

namespace {

std::size_t checked_window(int period, Estimator estimator) {
  require_period(period);
  if (estimator == Estimator::sample && period < 2) {
    throw InvalidArgument("a sample variance needs a period of at least 2, got " +
                          std::to_string(period));
  }
  return static_cast<std::size_t>(period);
}

double divisor(int period, Estimator estimator) {
  return static_cast<double>(estimator == Estimator::sample ? period - 1 : period);
}

// Four partial sums, each taking every fourth value and combined in a fixed order, let the
// additions proceed side by side.
template <typename Term>
double interleaved_sum(std::span<const double> window, Term term) {
  double first = 0.0, second = 0.0, third = 0.0, fourth = 0.0;
  auto value = window.begin();
  for (; window.end() - value >= 4; value += 4) {
    first += term(value[0]);
    second += term(value[1]);
    third += term(value[2]);
    fourth += term(value[3]);
  }
  if (value != window.end()) {
    first += term(*value++);
  }
  if (value != window.end()) {
    second += term(*value++);
  }
  if (value != window.end()) {
    third += term(*value);
  }
  return (first + second) + (third + fourth);
}

// Deviations are taken from the window's newest value, so equal values contribute exact zeros, and
// the mean deviation is removed in a second pass.
double window_variance(std::span<const double> window, double divisor) {
  const double anchor = window.back();
  const double mean = interleaved_sum(window, [anchor](double value) { return value - anchor; }) /
                      static_cast<double>(window.size());
  return interleaved_sum(window,
                         [anchor, mean](double value) {
                           const double deviation = (value - anchor) - mean;
                           return deviation * deviation;
                         }) /
         divisor;
}

}  // namespace

void variance(std::span<const double> values, int period, Estimator estimator,
              std::span<double> out) {
  const auto window = checked_window(period, estimator);
  require_same_length(values.size(), out.size());
  const double divide_by = divisor(period, estimator);
  std::size_t missing_count = 0;
  for (std::size_t index = 0; index < values.size(); ++index) {
    if (is_missing(values[index])) {
      ++missing_count;
    }
    if (index >= window && is_missing(values[index - window])) {
      --missing_count;
    }
    out[index] = index + 1 < window || missing_count > 0
                     ? missing
                     : window_variance(values.subspan(index + 1 - window, window), divide_by);
  }
}

void variance(const SeriesBatch& values, int period, Estimator estimator, std::span<double> out,
              unsigned threads) {
  checked_window(period, estimator);
  detail::over_series(values, period, out, threads, [estimator](auto series, int p, auto result) {
    variance(series, p, estimator, result);
  });
}

VarianceState::VarianceState(int period, Estimator estimator)
    : window_(2 * checked_window(period, estimator), 0.0),
      period_(window_.size() / 2),
      divisor_(divisor(period, estimator)) {}

double VarianceState::update(double value) {
  if (seen_ >= period_ && is_missing(window_[next_])) {
    --missing_;
  }
  if (is_missing(value)) {
    ++missing_;
  }
  window_[next_] = value;
  window_[next_ + period_] = value;
  next_ = (next_ + 1) % period_;
  ++seen_;
  if (seen_ < period_ || missing_ > 0) {
    return missing;
  }
  return window_variance(std::span<const double>(window_).subspan(next_, period_), divisor_);
}

}  // namespace btcore
