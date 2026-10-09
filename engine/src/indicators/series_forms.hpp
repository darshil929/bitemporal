#pragma once

#include <btcore/parallel.hpp>
#include <btcore/types.hpp>
#include <cmath>
#include <cstddef>
#include <span>

namespace btcore::detail {

/// Neumaier's compensated summation: the rounding error of each addition is carried separately and
/// added back when the total is read.
inline void accumulate(double& total, double& compensation, double value) {
  const double sum = total + value;
  if (std::fabs(total) >= std::fabs(value)) {
    compensation += (total - sum) + value;
  } else {
    compensation += (value - sum) + total;
  }
  total = sum;
}

/// The variance of one window: its squared deviations summed and divided by `divisor`. A window of
/// equal values gives exactly 0.
[[nodiscard]] double window_variance(std::span<const double> window, double divisor);

/// The universe form of a computation: its batch form over every series, spread over threads.
template <typename Batch>
void over_series(const SeriesBatch& values, int period, std::span<double> out, unsigned threads,
                 Batch batch) {
  require_period(period);
  require_same_length(values.values().size(), out.size());
  parallel_for(values.size(), threads, [&](std::size_t index) {
    batch(values.series(index), period, values.series(out, index));
  });
}

}  // namespace btcore::detail
