#include <benchmark/benchmark.h>

#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <cstdint>
#include <vector>

#include "full_history.hpp"

namespace {

using btcore::testing::full_history;

void VolumeRatio20(benchmark::State& state) {
  const auto& history = full_history();
  const btcore::SeriesBatch batch(history.values, history.offsets);
  std::vector<double> out(history.values.size());
  const auto threads = static_cast<unsigned>(state.range(0));
  for (auto _ : state) {
    btcore::ratio_to_prior_mean(batch, 20, out, threads);
    benchmark::DoNotOptimize(out.data());
    benchmark::ClobberMemory();
  }
  state.SetItemsProcessed(state.iterations() * static_cast<std::int64_t>(history.values.size()));
}

BENCHMARK(VolumeRatio20)->Arg(1)->Arg(8)->UseRealTime()->Unit(benchmark::kMillisecond);

void OnBalanceVolume(benchmark::State& state) {
  const auto& history = full_history();
  const btcore::SeriesBatch batch(history.values, history.offsets);
  std::vector<double> out(history.values.size());
  const auto threads = static_cast<unsigned>(state.range(0));
  for (auto _ : state) {
    btcore::on_balance_volume(batch, history.values, out, threads);
    benchmark::DoNotOptimize(out.data());
    benchmark::ClobberMemory();
  }
  state.SetItemsProcessed(state.iterations() * static_cast<std::int64_t>(history.values.size()));
}

BENCHMARK(OnBalanceVolume)->Arg(1)->Arg(8)->UseRealTime()->Unit(benchmark::kMillisecond);

}  // namespace
