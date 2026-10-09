#pragma once

#include <btcore/types.hpp>
#include <cstddef>
#include <span>
#include <vector>

namespace btcore {

/// Simple moving average: the mean of the last `period` values. The first `period - 1` outputs are
/// missing, and so is every output whose window holds a missing value. The running sum is
/// compensated, so a long series accumulates no rounding drift.
void sma(std::span<const double> values, int period, std::span<double> out);

/// The batch form over every series of `values`, spread over `threads` threads (0: all hardware).
void sma(const SeriesBatch& values, int period, std::span<double> out, unsigned threads);

/// The simple moving average one value at a time, equal bit for bit to the batch form.
class SmaState {
 public:
  explicit SmaState(int period);

  [[nodiscard]] double update(double value);

 private:
  std::vector<double> window_;
  std::size_t next_ = 0;
  std::size_t seen_ = 0;
  std::size_t missing_ = 0;
  double total_ = 0.0;
  double compensation_ = 0.0;
};

}  // namespace btcore
