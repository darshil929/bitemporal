#include <btcore/indicators.hpp>

#include "series_forms.hpp"

namespace btcore {

namespace {

double ratio(double value, double prior_mean) {
  return is_missing(prior_mean) ? missing : value / prior_mean;
}

}  // namespace

// The moving average is written into `out` first, then each value divides the average that ends
// on the bar before it, newest first, so every average is read before it is replaced.
void ratio_to_prior_mean(std::span<const double> values, int period, std::span<double> out) {
  sma(values, period, out);
  const auto window = static_cast<std::size_t>(period);
  for (std::size_t index = out.size(); index-- > 0;) {
    out[index] = index < window ? missing : ratio(values[index], out[index - 1]);
  }
}

void ratio_to_prior_mean(const SeriesBatch& values, int period, std::span<double> out,
                         unsigned threads) {
  detail::over_series(values, period, out, threads, [](auto series, int p, auto result) {
    ratio_to_prior_mean(series, p, result);
  });
}

PriorMeanRatioState::PriorMeanRatioState(int period) : mean_(period) {}

double PriorMeanRatioState::update(double value) {
  const double result = ratio(value, prior_mean_);
  prior_mean_ = mean_.update(value);
  return result;
}

void percentage_of(std::span<const double> parts, std::span<const double> wholes,
                   std::span<double> out) {
  require_same_length(parts.size(), wholes.size());
  require_same_length(parts.size(), out.size());
  for (std::size_t index = 0; index < parts.size(); ++index) {
    out[index] = percentage(parts[index], wholes[index]);
  }
}

}  // namespace btcore
