#include <benchmark/benchmark.h>

#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <cstdint>
#include <vector>

#include "full_history.hpp"

namespace {

using btcore::testing::full_history;

void Bollinger20(benchmark::State& state) {
  const auto& history = full_history();
  const btcore::SeriesBatch batch(history.values, history.offsets);
  std::vector<double> upper(history.values.size());
  std::vector<double> lower(history.values.size());
  const auto threads = static_cast<unsigned>(state.range(0));
  for (auto _ : state) {
    btcore::bollinger_bands(batch, 20, 2.0, upper, lower, threads);
    benchmark::DoNotOptimize(upper.data());
    benchmark::DoNotOptimize(lower.data());
    benchmark::ClobberMemory();
  }
  state.SetItemsProcessed(state.iterations() * static_cast<std::int64_t>(history.values.size()));
}

BENCHMARK(Bollinger20)->Arg(1)->Arg(8)->UseRealTime()->Unit(benchmark::kMillisecond);

}  // namespace
