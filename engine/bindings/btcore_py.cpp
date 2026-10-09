#include <nanobind/nanobind.h>
#include <nanobind/ndarray.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/string_view.h>

#include <algorithm>
#include <btcore/indicators.hpp>
#include <btcore/types.hpp>
#include <btcore/venues.hpp>
#include <btcore/version.hpp>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <span>
#include <utility>
#include <vector>

namespace nb = nanobind;
using namespace nb::literals;

namespace {

// Each array is borrowed as it stands: one that would need converting to float64, to contiguous
// memory or to the CPU is refused rather than copied.
using Values = nb::ndarray<const double, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using Offsets = nb::ndarray<const std::int64_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using Output = nb::ndarray<double, nb::numpy, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using Days = nb::ndarray<const std::int64_t, nb::ndim<1>, nb::c_contig, nb::device::cpu>;
using VenueCodes = nb::ndarray<std::int8_t, nb::numpy, nb::ndim<1>, nb::c_contig, nb::device::cpu>;

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
    throw btcore::InvalidArgument("out shares memory with values or another output");
  }
}

// Runs `series_form(input, output)` on one series, or `universe_form(batch, output)` on every
// series the offsets mark, with the GIL released.
template <typename SeriesCompute, typename UniverseCompute>
Output computed(const Values& values, const std::optional<Offsets>& offsets,
                std::optional<Output> out, SeriesCompute series_form,
                UniverseCompute universe_form) {
  Output result = out ? *std::move(out) : allocate(values.size());
  const std::span<const double> input(values.data(), values.size());
  const std::span<double> output(result.data(), result.size());
  require_disjoint(input, output);
  {
    const nb::gil_scoped_release release;
    if (offsets) {
      const btcore::SeriesBatch batch(input, {offsets->data(), offsets->size()});
      universe_form(batch, output);
    } else {
      series_form(input, output);
    }
  }
  return result;
}

template <SeriesForm series_form, UniverseForm universe_form>
Output windowed(const Values& values, int period, const std::optional<Offsets>& offsets,
                unsigned threads, std::optional<Output> out) {
  return computed(
      values, offsets, std::move(out),
      [period](auto input, auto output) { series_form(input, period, output); },
      [period, threads](const auto& batch, auto output) {
        universe_form(batch, period, output, threads);
      });
}

Output variance_binding(const Values& values, int period, bool sample,
                        const std::optional<Offsets>& offsets, unsigned threads,
                        std::optional<Output> out) {
  const auto estimator = sample ? btcore::Estimator::sample : btcore::Estimator::population;
  return computed(
      values, offsets, std::move(out),
      [=](auto input, auto output) { btcore::variance(input, period, estimator, output); },
      [=](const auto& batch, auto output) {
        btcore::variance(batch, period, estimator, output, threads);
      });
}

template <SeriesForm series_form, UniverseForm universe_form>
void def_windowed(nb::module_& module, const char* name, const char* doc,
                  const char* length = "period") {
  module.def(name, &windowed<series_form, universe_form>, "values"_a.noconvert(), nb::arg(length),
             nb::kw_only(), "offsets"_a.noconvert() = nb::none(), "threads"_a = 0,
             "out"_a.noconvert() = nb::none(), doc);
}

using Lines = std::pair<Output, Output>;

Lines bollinger_binding(const Values& values, int period, double width,
                        const std::optional<Offsets>& offsets, unsigned threads,
                        std::optional<Lines> out) {
  Output upper = out ? out->first : allocate(values.size());
  Output lower = out ? out->second : allocate(values.size());
  const std::span<const double> input(values.data(), values.size());
  const std::span<double> upper_line(upper.data(), upper.size());
  const std::span<double> lower_line(lower.data(), lower.size());
  require_disjoint(input, upper_line);
  require_disjoint(input, lower_line);
  require_disjoint(upper_line, lower_line);
  {
    const nb::gil_scoped_release release;
    if (offsets) {
      const btcore::SeriesBatch batch(input, {offsets->data(), offsets->size()});
      btcore::bollinger_bands(batch, period, width, upper_line, lower_line, threads);
    } else {
      btcore::bollinger_bands(input, period, width, upper_line, lower_line);
    }
  }
  return {upper, lower};
}

Output return_binding(const Values& values, int bars, int skip,
                      const std::optional<Offsets>& offsets, unsigned threads,
                      std::optional<Output> out) {
  return computed(
      values, offsets, std::move(out),
      [=](auto input, auto output) { btcore::simple_return(input, bars, skip, output); },
      [=](const auto& batch, auto output) {
        btcore::simple_return(batch, bars, skip, output, threads);
      });
}

Output volatility_binding(const Values& values, int period, int periods_per_year,
                          const std::optional<Offsets>& offsets, unsigned threads,
                          std::optional<Output> out) {
  return computed(
      values, offsets, std::move(out),
      [=](auto input, auto output) {
        btcore::realised_volatility(input, period, periods_per_year, output);
      },
      [=](const auto& batch, auto output) {
        btcore::realised_volatility(batch, period, periods_per_year, output, threads);
      });
}

template <btcore::Extreme extreme>
void extreme_of(std::span<const double> values, int period, std::span<double> out) {
  btcore::rolling_extreme(values, period, extreme, out);
}

template <btcore::Extreme extreme>
void extreme_of(const btcore::SeriesBatch& values, int period, std::span<double> out,
                unsigned threads) {
  btcore::rolling_extreme(values, period, extreme, out, threads);
}

template <btcore::Extreme extreme>
void new_extreme_of(std::span<const double> values, int period, std::span<double> out) {
  btcore::new_extreme(values, period, extreme, out);
}

template <btcore::Extreme extreme>
void new_extreme_of(const btcore::SeriesBatch& values, int period, std::span<double> out,
                    unsigned threads) {
  btcore::new_extreme(values, period, extreme, out, threads);
}

Output distance_binding(const Values& values, const Values& highs, int period,
                        const std::optional<Offsets>& offsets, unsigned threads,
                        std::optional<Output> out) {
  const std::span<const double> high_line(highs.data(), highs.size());
  return computed(
      values, offsets, std::move(out),
      [=](auto input, auto output) {
        require_disjoint(high_line, output);
        btcore::distance_from_high(input, high_line, period, output);
      },
      [=](const auto& batch, auto output) {
        require_disjoint(high_line, output);
        btcore::distance_from_high(batch, high_line, period, output, threads);
      });
}

Output percentage_binding(const Values& parts, const Values& wholes, std::optional<Output> out) {
  Output result = out ? *std::move(out) : allocate(parts.size());
  const std::span<const double> part_line(parts.data(), parts.size());
  const std::span<const double> whole_line(wholes.data(), wholes.size());
  const std::span<double> output(result.data(), result.size());
  require_disjoint(part_line, output);
  require_disjoint(whole_line, output);
  {
    const nb::gil_scoped_release release;
    btcore::percentage_of(part_line, whole_line, output);
  }
  return result;
}

Output volume_flow_binding(const Values& closes, const Values& volumes,
                           const std::optional<Offsets>& offsets, unsigned threads,
                           std::optional<Output> out) {
  const std::span<const double> volume_line(volumes.data(), volumes.size());
  return computed(
      closes, offsets, std::move(out),
      [=](auto input, auto output) {
        require_disjoint(volume_line, output);
        btcore::on_balance_volume(input, volume_line, output);
      },
      [=](const auto& batch, auto output) {
        require_disjoint(volume_line, output);
        btcore::on_balance_volume(batch, volume_line, output, threads);
      });
}

VenueCodes venue_binding(const Days& days, const Values& bse_turnover, const Values& nse_turnover,
                         const std::optional<Offsets>& offsets, unsigned threads) {
  const std::span<const std::int64_t> day_line(days.data(), days.size());
  const std::span<const double> bse_line(bse_turnover.data(), bse_turnover.size());
  const std::span<const double> nse_line(nse_turnover.data(), nse_turnover.size());
  std::vector<btcore::Venue> venues(days.size());
  {
    const nb::gil_scoped_release release;
    if (offsets) {
      btcore::primary_venue(day_line, bse_line, nse_line, {offsets->data(), offsets->size()},
                            venues, threads);
    } else {
      btcore::primary_venue(day_line, bse_line, nse_line, venues);
    }
  }
  auto codes = nb::cast<VenueCodes>(
      nb::module_::import_("numpy").attr("empty")(venues.size(), "dtype"_a = "int8"), false);
  const std::span<std::int8_t> code_line(codes.data(), codes.size());
  std::transform(venues.begin(), venues.end(), code_line.begin(),
                 [](btcore::Venue venue) { return static_cast<std::int8_t>(venue); });
  return codes;
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

  def_windowed<btcore::rsi, btcore::rsi>(
      m, "rsi",
      "Relative strength index of each series, 0 to 100, from Wilder's averages of its gains and "
      "losses seeded with the mean of the first period changes. The first period values of a "
      "series "
      "are NaN, and so is every value until the series first moves; a NaN yields NaN and the "
      "warm-up "
      "starts again after it.\n\n"
      "offsets, threads and out are as for sma.");

  m.def("variance", &variance_binding, "values"_a.noconvert(), "period"_a, nb::kw_only(),
        "sample"_a = false, "offsets"_a.noconvert() = nb::none(), "threads"_a = 0,
        "out"_a.noconvert() = nb::none(),
        "Variance of the last period values of each series, dividing by period, or by period - 1 "
        "when sample is true. The first period - 1 values of a series are NaN, and so is every "
        "value whose window holds a NaN; a window of equal values gives exactly 0.\n\n"
        "offsets, threads and out are as for sma.");

  m.def("bollinger_bands", &bollinger_binding, "values"_a.noconvert(), "period"_a, nb::kw_only(),
        "width"_a = 2.0, "offsets"_a.noconvert() = nb::none(), "threads"_a = 0,
        "out"_a.noconvert() = nb::none(),
        "Bollinger bands of each series, returned as (upper, lower): the simple moving average "
        "plus and minus width population standard deviations of the same period values. The first "
        "period - 1 values of a series are NaN, and so is every value whose window holds a NaN.\n\n"
        "out is a pair of arrays receiving (upper, lower); offsets and threads are as for sma.");

  m.def("simple_return", &return_binding, "values"_a.noconvert(), "bars"_a, nb::kw_only(),
        "skip"_a = 0, "offsets"_a.noconvert() = nb::none(), "threads"_a = 0,
        "out"_a.noconvert() = nb::none(),
        "Fractional return over bars values ending skip values back, (later - earlier) / earlier. "
        "The first bars + skip values of a series are NaN, and so is every value where either end "
        "is NaN.\n\n"
        "offsets, threads and out are as for sma.");

  m.def("realised_volatility", &volatility_binding, "values"_a.noconvert(), "period"_a,
        nb::kw_only(), "periods_per_year"_a = 252, "offsets"_a.noconvert() = nb::none(),
        "threads"_a = 0, "out"_a.noconvert() = nb::none(),
        "Realised volatility of each series: the sample standard deviation of its last period "
        "daily log returns, times the square root of periods_per_year. The logarithm returns the "
        "same bits on every platform. The first period values of a series are NaN, and so is every "
        "value whose window holds a NaN return.\n\n"
        "offsets, threads and out are as for sma.");

  def_windowed<btcore::change, btcore::change>(
      m, "change",
      "Each value less the value bars before it. The first bars values of a series are NaN, and so "
      "is every value where either end is NaN.\n\n"
      "offsets, threads and out are as for sma.",
      "bars");

  def_windowed<extreme_of<btcore::Extreme::maximum>, extreme_of<btcore::Extreme::maximum>>(
      m, "rolling_maximum",
      "Largest of the last period values of each series. The first period - 1 values of a series "
      "are NaN, and so is every value whose window holds a NaN.\n\n"
      "offsets, threads and out are as for sma.");

  def_windowed<extreme_of<btcore::Extreme::minimum>, extreme_of<btcore::Extreme::minimum>>(
      m, "rolling_minimum",
      "Smallest of the last period values of each series, as for rolling_maximum.\n\n"
      "offsets, threads and out are as for sma.");

  m.def("distance_from_high", &distance_binding, "values"_a.noconvert(), "highs"_a.noconvert(),
        "period"_a, nb::kw_only(), "offsets"_a.noconvert() = nb::none(), "threads"_a = 0,
        "out"_a.noconvert() = nb::none(),
        "Fractional distance of each value from the highest of the last period highs, the day's "
        "own among them: (value - highest) / highest. The first period - 1 values of a series are "
        "NaN, and so is every value where it or a high in the window is NaN.\n\n"
        "highs is laid out like values; offsets, threads and out are as for sma.");

  def_windowed<new_extreme_of<btcore::Extreme::maximum>, new_extreme_of<btcore::Extreme::maximum>>(
      m, "new_high",
      "1.0 where a value is at or above every one of the period - 1 values before it, 0.0 where "
      "not. The first period - 1 values of a series are NaN, and so is every value whose window "
      "holds a NaN.\n\n"
      "offsets, threads and out are as for sma.");

  def_windowed<new_extreme_of<btcore::Extreme::minimum>, new_extreme_of<btcore::Extreme::minimum>>(
      m, "new_low",
      "1.0 where a value is at or below every one of the period - 1 values before it, as for "
      "new_high.\n\n"
      "offsets, threads and out are as for sma.");

  def_windowed<btcore::ratio_to_prior_mean, btcore::ratio_to_prior_mean>(
      m, "ratio_to_prior_mean",
      "Each value over the mean of the period values before it. The first period values of a "
      "series are NaN, and so is every value where it or one of those before it is NaN.\n\n"
      "offsets, threads and out are as for sma.");

  m.def("percentage_of", &percentage_binding, "parts"_a.noconvert(), "wholes"_a.noconvert(),
        nb::kw_only(), "out"_a.noconvert() = nb::none(),
        "Each part as a percentage of its whole, part / whole * 100; NaN where either is NaN. It "
        "reads no window, so one call covers any number of series laid end to end.");

  m.def(
      "on_balance_volume", &volume_flow_binding, "closes"_a.noconvert(), "volumes"_a.noconvert(),
      nb::kw_only(), "offsets"_a.noconvert() = nb::none(), "threads"_a = 0,
      "out"_a.noconvert() = nb::none(),
      "On-balance volume of each series: from the first volume, each volume added on a higher "
      "close, subtracted on a lower one and held on an unchanged one. A NaN close or volume gives "
      "NaN, and the total starts again after it.\n\n"
      "volumes is laid out like closes; offsets, threads and out are as for sma.");

  m.def(
      "primary_venue", &venue_binding, "days"_a.noconvert(), "bse_turnover"_a.noconvert(),
      "nse_turnover"_a.noconvert(), nb::kw_only(), "offsets"_a.noconvert() = nb::none(),
      "threads"_a = 0,
      "Primary venue of each day as int8, 0 for BSE and 1 for NSE: the larger "
      "turnover over the 90 calendar days ending on the last day of the month before, or, in the "
      "first month and in a month whose 90 days hold no turnover, from the month's first day "
      "through the day; a tie goes to BSE. days counts days from 1970-01-01, as "
      "datetime64[D].view('int64') gives them, and rises strictly; a venue's turnover is NaN on a "
      "day it did not trade.\n\n"
      "offsets and threads are as for sma.");
}
