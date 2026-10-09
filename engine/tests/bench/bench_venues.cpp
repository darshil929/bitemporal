#include <benchmark/benchmark.h>

#include <btcore/venues.hpp>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "full_history.hpp"

namespace {

using btcore::testing::full_history;
using btcore::testing::kHistoryBars;

// 2016-01-01, counted from 1970-01-01.
constexpr std::int64_t kFirstDay = 16'801;

// Each series trades every calendar day from the first, its NSE turnover the next series' values.
struct VenueHistory {
  std::vector<std::int64_t> days;
  std::vector<double> nse_turnover;
};

const VenueHistory& venue_history() {
  static const VenueHistory history = [] {
    const auto& drawn = full_history();
    VenueHistory built;
    built.days.reserve(drawn.values.size());
    for (std::size_t row = 0; row < drawn.values.size(); ++row) {
      built.days.push_back(kFirstDay + static_cast<std::int64_t>(row % kHistoryBars));
    }
    built.nse_turnover.assign(drawn.values.begin() + kHistoryBars, drawn.values.end());
    built.nse_turnover.insert(built.nse_turnover.end(), drawn.values.begin(),
                              drawn.values.begin() + kHistoryBars);
    return built;
  }();
  return history;
}

void PrimaryVenue(benchmark::State& state) {
  const auto& drawn = full_history();
  const auto& venues = venue_history();
  std::vector<btcore::Venue> out(drawn.values.size());
  const auto threads = static_cast<unsigned>(state.range(0));
  for (auto _ : state) {
    btcore::primary_venue(venues.days, drawn.values, venues.nse_turnover, drawn.offsets, out,
                          threads);
    benchmark::DoNotOptimize(out.data());
    benchmark::ClobberMemory();
  }
  state.SetItemsProcessed(state.iterations() * static_cast<std::int64_t>(drawn.values.size()));
}

BENCHMARK(PrimaryVenue)->Arg(1)->Arg(8)->UseRealTime()->Unit(benchmark::kMillisecond);

// Consecutive series pair up as one instrument's BSE and NSE bars, trading the same days.
void DesignatedBars(benchmark::State& state) {
  const auto& drawn = full_history();
  const auto& venues = venue_history();
  std::vector<std::uint8_t> out(drawn.values.size());
  const auto threads = static_cast<unsigned>(state.range(0));
  for (auto _ : state) {
    btcore::designated_bars(venues.days, drawn.values, drawn.offsets, out, threads);
    benchmark::DoNotOptimize(out.data());
    benchmark::ClobberMemory();
  }
  state.SetItemsProcessed(state.iterations() * static_cast<std::int64_t>(drawn.values.size()));
}

BENCHMARK(DesignatedBars)->Arg(1)->Arg(8)->UseRealTime()->Unit(benchmark::kMillisecond);

}  // namespace
