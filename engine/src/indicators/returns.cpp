#include <btcore/indicators.hpp>
#include <string>

#include "series_forms.hpp"

namespace btcore {

namespace {

std::size_t checked_skip(int skip) {
  if (skip < 0) {
    throw InvalidArgument("skip must not be negative, got " + std::to_string(skip));
  }
  return static_cast<std::size_t>(skip);
}

std::size_t checked_bars(int bars) {
  require_period(bars);
  return static_cast<std::size_t>(bars);
}

double fractional_return(double later, double earlier) { return (later - earlier) / earlier; }

}  // namespace

void simple_return(std::span<const double> values, int bars, int skip, std::span<double> out) {
  const auto distance = checked_bars(bars);
  const auto lag = checked_skip(skip);
  require_same_length(values.size(), out.size());
  for (std::size_t index = 0; index < values.size(); ++index) {
    out[index] = index < distance + lag
                     ? missing
                     : fractional_return(values[index - lag], values[index - lag - distance]);
  }
}

void simple_return(const SeriesBatch& values, int bars, int skip, std::span<double> out,
                   unsigned threads) {
  checked_skip(skip);
  detail::over_series(values, bars, out, threads, [skip](auto series, int b, auto result) {
    simple_return(series, b, skip, result);
  });
}

Lookback::Lookback(std::size_t distance) : values_(distance, missing) {}

double Lookback::push(double value) {
  if (values_.empty()) {
    return value;
  }
  const double earlier = values_[next_];
  values_[next_] = value;
  next_ = (next_ + 1) % values_.size();
  return earlier;
}

ReturnState::ReturnState(int bars, int skip)
    : later_(checked_skip(skip)), earlier_(checked_bars(bars)) {}

double ReturnState::update(double value) {
  const double later = later_.push(value);
  return fractional_return(later, earlier_.push(later));
}

}  // namespace btcore
