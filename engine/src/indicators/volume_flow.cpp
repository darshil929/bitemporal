#include <btcore/indicators.hpp>
#include <btcore/parallel.hpp>

#include "series_forms.hpp"

namespace btcore {

void on_balance_volume(std::span<const double> closes, std::span<const double> volumes,
                       std::span<double> out) {
  require_same_length(closes.size(), volumes.size());
  require_same_length(closes.size(), out.size());
  OnBalanceVolumeState state;
  for (std::size_t index = 0; index < closes.size(); ++index) {
    out[index] = state.update(closes[index], volumes[index]);
  }
}

void on_balance_volume(const SeriesBatch& closes, std::span<const double> volumes,
                       std::span<double> out, unsigned threads) {
  require_same_length(closes.values().size(), out.size());
  parallel_for(closes.size(), threads, [&](std::size_t index) {
    on_balance_volume(closes.series(index), closes.input_series(volumes, index),
                      closes.series(out, index));
  });
}

double OnBalanceVolumeState::update(double close, double volume) {
  if (is_missing(close) || is_missing(volume)) {
    started_ = false;
    return missing;
  }
  if (!started_) {
    started_ = true;
    total_ = volume;
    compensation_ = 0.0;
  } else if (close > previous_close_) {
    detail::accumulate(total_, compensation_, volume);
  } else if (close < previous_close_) {
    detail::accumulate(total_, compensation_, -volume);
  }
  previous_close_ = close;
  return total_ + compensation_;
}

}  // namespace btcore
