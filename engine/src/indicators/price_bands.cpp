#include <btcore/indicators.hpp>
#include <btcore/parallel.hpp>
#include <cmath>
#include <string>

namespace btcore {

namespace {

void require_width(double width) {
  if (!std::isfinite(width) || width < 0.0) {
    throw InvalidArgument("band width must be finite and not negative, got " +
                          std::to_string(width));
  }
}

Band band(double average, double variance, double width) {
  const double spread = width * std::sqrt(variance);
  return {average + spread, average - spread};
}

}  // namespace

void bollinger_bands(std::span<const double> values, int period, double width,
                     std::span<double> upper, std::span<double> lower) {
  require_width(width);
  require_same_length(values.size(), lower.size());
  sma(values, period, upper);
  variance(values, period, Estimator::population, lower);
  for (std::size_t index = 0; index < values.size(); ++index) {
    const Band lines = band(upper[index], lower[index], width);
    upper[index] = lines.upper;
    lower[index] = lines.lower;
  }
}

void bollinger_bands(const SeriesBatch& values, int period, double width, std::span<double> upper,
                     std::span<double> lower, unsigned threads) {
  require_period(period);
  require_width(width);
  require_same_length(values.values().size(), upper.size());
  require_same_length(values.values().size(), lower.size());
  parallel_for(values.size(), threads, [&](std::size_t index) {
    bollinger_bands(values.series(index), period, width, values.series(upper, index),
                    values.series(lower, index));
  });
}

BollingerState::BollingerState(int period, double width)
    : average_(period), variance_(period, Estimator::population), width_(width) {
  require_width(width);
}

Band BollingerState::update(double value) {
  const double average = average_.update(value);
  return band(average, variance_.update(value), width_);
}

}  // namespace btcore
