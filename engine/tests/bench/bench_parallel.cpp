#include <benchmark/benchmark.h>

#include <btcore/parallel.hpp>
#include <btcore/types.hpp>
#include <cstdint>
#include <vector>

#include "full_history.hpp"

namespace {

using btcore::testing::full_history;

// One pass over every series with a computation as light as a sum, which leaves the pool's own
// cost and the memory bandwidth in view.
void UniverseSum(benchmark::State& state) {
  const auto& history = full_history();
  const btcore::SeriesBatch batch(history.values, history.offsets);
  std::vector<double> sums(batch.size());
  const auto threads = static_cast<unsigned>(state.range(0));
  for (auto _ : state) {
    btcore::parallel_for(batch.size(), threads, [&](std::size_t index) {
      double total = 0.0;
      for (const double close : batch.series(index)) {
        total += close;
      }
      sums[index] = total;
    });
    benchmark::DoNotOptimize(sums.data());
    benchmark::ClobberMemory();
  }
  state.SetItemsProcessed(state.iterations() * static_cast<std::int64_t>(history.values.size()));
}

BENCHMARK(UniverseSum)
    ->Arg(1)
    ->Arg(2)
    ->Arg(4)
    ->Arg(8)
    ->UseRealTime()
    ->Unit(benchmark::kMillisecond);

}  // namespace
