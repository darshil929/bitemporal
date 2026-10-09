#include <btcore/indicators.hpp>
#include <btcore/maths.hpp>
#include <cmath>
#include <string>

#include "series_forms.hpp"

namespace btcore {

namespace {

std::size_t checked_window(int period) {
  if (period < 2) {
    throw InvalidArgument("realised volatility needs a period of at least 2, got " +
                          std::to_string(period));
  }
  return static_cast<std::size_t>(period);
}

double annualiser(int periods_per_year) {
  if (periods_per_year < 1) {
    throw InvalidArgument("periods per year must be at least 1, got " +
                          std::to_string(periods_per_year));
  }
  return std::sqrt(static_cast<double>(periods_per_year));
}

double annualised(double variance, double scale) {
  return is_missing(variance) ? missing : std::sqrt(variance) * scale;
}

}  // namespace

// The daily log returns are written into `out` first, then each window of them is replaced by its
// volatility, newest first, so every window still reads returns.
void realised_volatility(std::span<const double> values, int period, int periods_per_year,
                         std::span<double> out) {
  const auto window = checked_window(period);
  const double scale = annualiser(periods_per_year);
  require_same_length(values.size(), out.size());
  for (std::size_t index = 0; index < values.size(); ++index) {
    out[index] =
        index == 0 ? missing : log1p((values[index] - values[index - 1]) / values[index - 1]);
  }
  for (std::size_t index = out.size(); index-- > 0;) {
    out[index] = index < window
                     ? missing
                     : annualised(detail::window_variance(out.subspan(index + 1 - window, window),
                                                          static_cast<double>(period - 1)),
                                  scale);
  }
}

void realised_volatility(const SeriesBatch& values, int period, int periods_per_year,
                         std::span<double> out, unsigned threads) {
  checked_window(period);
  annualiser(periods_per_year);
  detail::over_series(values, period, out, threads,
                      [periods_per_year](auto series, int p, auto result) {
                        realised_volatility(series, p, periods_per_year, result);
                      });
}

VolatilityState::VolatilityState(int period, int periods_per_year)
    : daily_(1, 0),
      variance_(static_cast<int>(checked_window(period)), Estimator::sample),
      annualiser_(annualiser(periods_per_year)) {}

double VolatilityState::update(double value) {
  return annualised(variance_.update(log1p(daily_.update(value))), annualiser_);
}

}  // namespace btcore
