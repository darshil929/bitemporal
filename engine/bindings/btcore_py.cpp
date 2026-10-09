#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/string_view.h>

#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <btcore/version.hpp>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <span>
#include <utility>

namespace nb = nanobind;
using namespace nb::literals;

namespace {

// Each array is borrowed as it stands: one that would need converting to float64, to contiguous
// memory or to the CPU is refused rather than copied.
using Values = nb::ndarray<const double, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using Offsets = nb::ndarray<const std::int64_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using Output = nb::ndarray<double, nb::numpy, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

using SeriesForm = void (*)(std::span<const double>, int, std::span<double>);
using UniverseForm = void (*)(const btcore::SeriesBatch&, int, std::span<double>, unsigned);

Output allocate(std::size_t length) {
  return nb::cast<Output>(nb::module_::import_("numpy").attr("empty")(length), false);
}

// A window reads values it has already passed, so an output sharing memory with its input would
// be read after it is written.
void require_disjoint(std::span<const double> input, std::span<const double> output) {
  const std::less<const double*> before;
  if (before(input.data(), std::to_address(output.end())) &&
      before(output.data(), std::to_address(input.end()))) {
    throw btcore::InvalidArgument("out shares memory with values");
  }
}

template <SeriesForm series_form, UniverseForm universe_form>
Output windowed(const Values& values, int period, const std::optional<Offsets>& offsets,
                unsigned threads, std::optional<Output> out) {
  Output result = out ? *std::move(out) : allocate(values.size());
  const std::span<const double> input(values.data(), values.size());
  const std::span<double> output(result.data(), result.size());
  require_disjoint(input, output);
  {
    const nb::gil_scoped_release release;
    if (offsets) {
      const btcore::SeriesBatch batch(input, {offsets->data(), offsets->size()});
      universe_form(batch, period, output, threads);
    } else {
      series_form(input, period, output);
    }
  }
  return result;
}

template <SeriesForm series_form, UniverseForm universe_form>
void def_windowed(nb::module_& module, const char* name, const char* doc) {
  module.def(name, &windowed<series_form, universe_form>, "values"_a.noconvert(), "period"_a,
             nb::kw_only(), "offsets"_a.noconvert() = nb::none(), "threads"_a = 0,
             "out"_a.noconvert() = nb::none(), doc);
}

}  // namespace

NB_MODULE(_btcore, m) {
  m.def("version", &btcore::version);

  def_windowed<btcore::sma, btcore::sma>(
      m, "sma",
      "Simple moving average of each series. The first period - 1 values of a series are NaN, and "
      "so is every value whose window holds a NaN.\n\n"
      "offsets marks where each series of values begins, the last entry equal to len(values); "
      "without it values is one series. threads spreads the series over that many threads, 0 "
      "meaning one per core. out receives the result in place of a new array.");

  def_windowed<btcore::ema, btcore::ema>(
      m, "ema",
      "Exponential moving average of each series, seeded with the simple average of its first "
      "period values. The first period - 1 values of a series are NaN; a NaN yields NaN and the "
      "average is seeded again from the values after it.\n\n"
      "offsets, threads and out are as for sma.");
}
