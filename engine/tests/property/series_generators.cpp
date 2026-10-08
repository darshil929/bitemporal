#include "series_generators.hpp"

#include <algorithm>
#include <array>
#include <cstdlib>
#include <limits>
#include <numeric>
#include <stdexcept>

namespace btcore::testing {

namespace {

constexpr std::uint64_t kDefaultSeed = 0x5eed;

// The standard distributions differ between standard libraries and the transcendental functions
// between maths libraries, so draws use the specified engine and arithmetic alone.
constexpr double kUnitBits = 0x1p-53;
constexpr int kNormalTerms = 12;
constexpr double kDailyVolatility = 0.02;
constexpr std::array<double, 7> kPriceBounds{0.5, 5.0, 50.0, 500.0, 5'000.0, 50'000.0, 100'000.0};

}  // namespace

std::uint64_t property_seed() {
  const char* configured = std::getenv("BTCORE_PROPERTY_SEED");
  return configured != nullptr ? std::stoull(configured) : kDefaultSeed;
}

double SeriesGenerator::uniform() { return static_cast<double>(engine_() >> 11) * kUnitBits; }

// Irwin-Hall: twelve uniform draws, less six, have mean 0 and standard deviation 1, within +-6.
double SeriesGenerator::normal() {
  double sum = 0.0;
  for (int term = 0; term < kNormalTerms; ++term) {
    sum += uniform();
  }
  return sum - kNormalTerms / 2.0;
}

double SeriesGenerator::price() {
  const auto span =
      static_cast<std::size_t>(uniform() * static_cast<double>(kPriceBounds.size() - 1));
  const double low = kPriceBounds.at(span);
  return low + (kPriceBounds.at(span + 1) - low) * uniform();
}

std::vector<double> SeriesGenerator::random_walk(std::size_t length, double start) {
  std::vector<double> values(length);
  double close = start;
  for (double& value : values) {
    value = close;
    close *= 1.0 + kDailyVolatility * normal();
  }
  return values;
}

void SeriesGenerator::punch_gaps(std::vector<double>& values, std::size_t count) {
  std::vector<std::size_t> positions(values.size());
  std::iota(positions.begin(), positions.end(), std::size_t{0});
  const std::size_t gaps = std::min(count, values.size());
  for (std::size_t chosen = 0; chosen < gaps; ++chosen) {
    const std::size_t remaining = positions.size() - chosen;
    const auto pick = chosen + static_cast<std::size_t>(uniform() * static_cast<double>(remaining));
    std::swap(positions[chosen], positions[pick]);
    values[positions[chosen]] = std::numeric_limits<double>::quiet_NaN();
  }
}

std::vector<SeriesCase> window_cases(int period, std::uint64_t seed) {
  if (period < 1) {
    throw std::invalid_argument("period must be at least 1");
  }
  SeriesGenerator generator(seed);
  const auto window = static_cast<std::size_t>(period);
  const std::size_t longest = 3 * window + 5;
  std::vector<SeriesCase> cases;

  for (std::size_t length = 0; length <= longest; ++length) {
    cases.push_back({"walk of " + std::to_string(length) + " bars",
                     generator.random_walk(length, generator.price())});
  }

  cases.push_back({"flat", std::vector<double>(longest, generator.price())});

  auto stalled = generator.random_walk(longest + window, generator.price());
  std::fill(stalled.begin() + period, stalled.begin() + 2 * period + 1, stalled[window - 1]);
  cases.push_back({"walk holding a flat stretch", std::move(stalled)});

  for (const std::size_t gaps : {std::size_t{1}, std::size_t{3}}) {
    auto gapped = generator.random_walk(longest, generator.price());
    generator.punch_gaps(gapped, gaps);
    cases.push_back({"walk with " + std::to_string(gaps) + " missing", std::move(gapped)});
  }
  return cases;
}

Universe universe(std::size_t series, std::size_t length, std::uint64_t seed) {
  SeriesGenerator generator(seed);
  Universe result;
  result.values.reserve(series * length);
  result.offsets.reserve(series + 1);
  result.offsets.push_back(0);
  for (std::size_t index = 0; index < series; ++index) {
    const auto walk = generator.random_walk(length, generator.price());
    result.values.insert(result.values.end(), walk.begin(), walk.end());
    result.offsets.push_back(static_cast<std::int64_t>(result.values.size()));
  }
  return result;
}

}  // namespace btcore::testing
