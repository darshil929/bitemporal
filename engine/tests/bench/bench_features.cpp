#include <benchmark/benchmark.h>

#include <btcore/features.hpp>
#include <cstdint>
#include <vector>

#include "full_history.hpp"

namespace {

using btcore::testing::full_history;

void DailyFeatures(benchmark::State& state) {
  const auto& history = full_history();
  const std::vector<double> factor(history.values.size(), 1.0);
  const btcore::DailyBars bars{history.values, factor};
  std::vector<double> out(history.values.size() * btcore::feature_count);
  const auto threads = static_cast<unsigned>(state.range(0));
  for (auto _ : state) {
    btcore::daily_features(bars, history.offsets, out, threads);
    benchmark::DoNotOptimize(out.data());
    benchmark::ClobberMemory();
  }
  state.SetItemsProcessed(state.iterations() * static_cast<std::int64_t>(history.values.size()));
}

BENCHMARK(DailyFeatures)->Arg(1)->Arg(8)->UseRealTime()->Unit(benchmark::kMillisecond);

}  // namespace
