#include <btcore/indicators.hpp>

#include "series_forms.hpp"

namespace btcore {

namespace {

std::size_t checked_period(int period) {
  require_period(period);
  return static_cast<std::size_t>(period);
}

}  // namespace

void rolling_extreme(std::span<const double> values, int period, Extreme extreme,
                     std::span<double> out) {
  require_same_length(values.size(), out.size());
  RollingExtremeState state(period, extreme);
  for (std::size_t index = 0; index < values.size(); ++index) {
    out[index] = state.update(values[index]);
  }
}

void rolling_extreme(const SeriesBatch& values, int period, Extreme extreme, std::span<double> out,
                     unsigned threads) {
  detail::over_series(values, period, out, threads, [extreme](auto series, int p, auto result) {
    rolling_extreme(series, p, extreme, result);
  });
}

RollingExtremeState::RollingExtremeState(int period, Extreme extreme)
    : held_(checked_period(period), 0.0),
      held_at_(held_.size(), 0),
      was_missing_(held_.size(), 0),
      period_(held_.size()),
      extreme_(extreme) {}

bool RollingExtremeState::keeps(double held, double arriving) const {
  return extreme_ == Extreme::maximum ? held > arriving : held < arriving;
}

// Every index below is under twice the period, so one subtraction wraps it into the rings.
std::size_t RollingExtremeState::wrapped(std::size_t index) const {
  return index >= period_ ? index - period_ : index;
}

double RollingExtremeState::update(double value) {
  const std::size_t position = seen_++;
  if (position >= period_ && was_missing_[slot_] != 0) {
    --missing_;
  }
  was_missing_[slot_] = is_missing(value) ? 1 : 0;
  slot_ = wrapped(slot_ + 1);
  if (size_ > 0 && held_at_[head_] + period_ <= position) {
    head_ = wrapped(head_ + 1);
    --size_;
  }
  if (is_missing(value)) {
    ++missing_;
  } else {
    while (size_ > 0 && !keeps(held_[wrapped(head_ + size_ - 1)], value)) {
      --size_;
    }
    const std::size_t back = wrapped(head_ + size_);
    held_[back] = value;
    held_at_[back] = position;
    ++size_;
  }
  return position + 1 < period_ || missing_ > 0 ? missing : held_[head_];
}

}  // namespace btcore
