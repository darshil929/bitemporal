#include <btcore/indicators.hpp>
#include <btcore/parallel.hpp>
#include <cmath>

namespace btcore {

namespace {

// Neumaier's compensated summation: the rounding error of each addition is carried separately and
// added back when the total is read.
void accumulate(double& total, double& compensation, double value) {
  const double sum = total + value;
  if (std::fabs(total) >= std::fabs(value)) {
    compensation += (total - sum) + value;
  } else {
    compensation += (value - sum) + total;
  }
  total = sum;
}

// A missing value is counted rather than summed, so it leaves the total untouched when it leaves
// the window.
void enter(double& total, double& compensation, std::size_t& missing_count, double value) {
  if (is_missing(value)) {
    ++missing_count;
  } else {
    accumulate(total, compensation, value);
  }
}

void leave(double& total, double& compensation, std::size_t& missing_count, double value) {
  if (is_missing(value)) {
    --missing_count;
  } else {
    accumulate(total, compensation, -value);
  }
}

double ema_step(double k, double value, double average) {
  return std::fma(k, value - average, average);
}

double smoothing(int period) { return 2.0 / (static_cast<double>(period) + 1.0); }

template <typename Batch>
void over_series(const SeriesBatch& values, int period, std::span<double> out, unsigned threads,
                 Batch batch) {
  require_period(period);
  require_same_length(values.values().size(), out.size());
  parallel_for(values.size(), threads, [&](std::size_t index) {
    batch(values.series(index), period, values.series(out, index));
  });
}

}  // namespace

void sma(std::span<const double> values, int period, std::span<double> out) {
  require_period(period);
  require_same_length(values.size(), out.size());
  const auto window = static_cast<std::size_t>(period);
  double total = 0.0;
  double compensation = 0.0;
  std::size_t missing_count = 0;
  for (std::size_t index = 0; index < values.size(); ++index) {
    enter(total, compensation, missing_count, values[index]);
    if (index >= window) {
      leave(total, compensation, missing_count, values[index - window]);
    }
    out[index] = index + 1 < window || missing_count > 0
                     ? missing
                     : (total + compensation) / static_cast<double>(period);
  }
}

void sma(const SeriesBatch& values, int period, std::span<double> out, unsigned threads) {
  over_series(values, period, out, threads,
              [](auto series, int p, auto result) { sma(series, p, result); });
}

SmaState::SmaState(int period) {
  require_period(period);
  window_.assign(static_cast<std::size_t>(period), 0.0);
}

double SmaState::update(double value) {
  enter(total_, compensation_, missing_, value);
  if (seen_ >= window_.size()) {
    leave(total_, compensation_, missing_, window_[next_]);
  }
  window_[next_] = value;
  next_ = (next_ + 1) % window_.size();
  ++seen_;
  return seen_ < window_.size() || missing_ > 0
             ? missing
             : (total_ + compensation_) / static_cast<double>(window_.size());
}

void ema(std::span<const double> values, int period, std::span<double> out) {
  require_period(period);
  require_same_length(values.size(), out.size());
  EmaState state(period);
  for (std::size_t index = 0; index < values.size(); ++index) {
    out[index] = state.update(values[index]);
  }
}

void ema(const SeriesBatch& values, int period, std::span<double> out, unsigned threads) {
  over_series(values, period, out, threads,
              [](auto series, int p, auto result) { ema(series, p, result); });
}

EmaState::EmaState(int period) : period_(period), k_(smoothing(period)) { require_period(period); }

double EmaState::update(double value) {
  if (is_missing(value)) {
    seeded_ = 0;
    seed_total_ = 0.0;
    return missing;
  }
  if (seeded_ < period_) {
    seed_total_ += value;
    ++seeded_;
    if (seeded_ < period_) {
      return missing;
    }
    average_ = seed_total_ / static_cast<double>(period_);
    return average_;
  }
  average_ = ema_step(k_, value, average_);
  return average_;
}

}  // namespace btcore
