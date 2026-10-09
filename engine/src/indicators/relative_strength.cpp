#include <btcore/indicators.hpp>

#include "series_forms.hpp"

namespace btcore {

void rsi(std::span<const double> values, int period, std::span<double> out) {
  require_period(period);
  require_same_length(values.size(), out.size());
  RsiState state(period);
  for (std::size_t index = 0; index < values.size(); ++index) {
    out[index] = state.update(values[index]);
  }
}

void rsi(const SeriesBatch& values, int period, std::span<double> out, unsigned threads) {
  detail::over_series(values, period, out, threads,
                      [](auto series, int p, auto result) { rsi(series, p, result); });
}

RsiState::RsiState(int period)
    : period_(period), inverse_period_(1.0 / static_cast<double>(period)) {
  require_period(period);
}

double RsiState::update(double value) {
  if (is_missing(value)) {
    *this = RsiState(period_);
    return missing;
  }
  if (!has_previous_) {
    has_previous_ = true;
    previous_ = value;
    return missing;
  }
  const double change = value - previous_;
  previous_ = value;
  const double gain = change > 0.0 ? change : 0.0;
  if (changes_ < period_) {
    gain_ += gain;
    loss_ += gain - change;
    if (++changes_ < period_) {
      return missing;
    }
  } else {
    gain_ *= static_cast<double>(period_ - 1);
    loss_ *= static_cast<double>(period_ - 1);
    gain_ += gain;
    loss_ += gain - change;
  }
  gain_ *= inverse_period_;
  loss_ *= inverse_period_;
  // Both averages are zero only while every change since the first value has been zero.
  const double movement = gain_ + loss_;
  return movement > 0.0 ? 100.0 * (gain_ / movement) : missing;
}

}  // namespace btcore
