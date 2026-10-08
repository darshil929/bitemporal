#pragma once

#include <cstddef>
#include <cstdint>
#include <random>
#include <string>
#include <vector>

namespace btcore::testing {

/// The seed property tests draw from: `BTCORE_PROPERTY_SEED` when set, otherwise a fixed value, so
/// a run is reproducible unless a fresh seed is asked for.
[[nodiscard]] std::uint64_t property_seed();

/// Series for property tests and benchmarks, the same for the same seed on every platform.
class SeriesGenerator {
 public:
  explicit SeriesGenerator(std::uint64_t seed) : engine_(seed) {}

  /// A price between 0.5 and 1,00,000, the range listed shares trade in: one of six spans, 0.5 to
  /// 5 up to 50,000 to 1,00,000, chosen evenly, then a point within it.
  [[nodiscard]] double price();

  /// Closes following daily log returns of two percent standard deviation from `start`.
  [[nodiscard]] std::vector<double> random_walk(std::size_t length, double start);

  /// Replaces `count` values at distinct random positions with missing values.
  void punch_gaps(std::vector<double>& values, std::size_t count);

 private:
  [[nodiscard]] double uniform();
  [[nodiscard]] double normal();

  std::mt19937_64 engine_;
};

/// One input of a property test, labelled with what produced it.
struct SeriesCase {
  std::string label;
  std::vector<double> values;
};

/// Inputs exercising a window of `period` bars: a random walk of every length from 0 to three
/// windows and five bars more, each at a fresh price; a flat series; a walk holding a flat stretch
/// longer than the window; and walks with missing values.
[[nodiscard]] std::vector<SeriesCase> window_cases(int period, std::uint64_t seed);

/// Many random walks laid end to end, with the offsets marking where each begins.
struct Universe {
  std::vector<double> values;
  std::vector<std::int64_t> offsets;
};

[[nodiscard]] Universe universe(std::size_t series, std::size_t length, std::uint64_t seed);

}  // namespace btcore::testing
