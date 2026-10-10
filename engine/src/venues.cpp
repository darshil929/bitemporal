#include <algorithm>
#include <btcore/parallel.hpp>
#include <btcore/venues.hpp>
#include <chrono>
#include <string>

namespace btcore {

namespace {

constexpr std::int64_t kWindowDays = 90;

std::int64_t month_start(std::int64_t day) {
  using namespace std::chrono;
  const year_month_day date{sys_days{days{static_cast<days::rep>(day)}}};
  return sys_days{date.year() / date.month() / 1}.time_since_epoch().count();
}

double traded(double turnover) { return is_missing(turnover) ? 0.0 : turnover; }

Venue larger(double bse, double nse) { return nse > bse ? Venue::nse : Venue::bse; }

// One instrument's bars at one venue, read in step with its bars at the other.
struct VenueBars {
  std::span<const std::int64_t> days;
  std::span<const double> turnover;
  std::span<std::uint8_t> out;
  std::size_t next = 0;

  [[nodiscard]] bool has_bars() const { return next < days.size(); }
  [[nodiscard]] bool trades_on(std::int64_t day) const { return has_bars() && days[next] == day; }
};

void designate(VenueBars bse, VenueBars nse) {
  PrimaryVenueState state;
  while (bse.has_bars() || nse.has_bars()) {
    const std::int64_t day = !nse.has_bars()   ? bse.days[bse.next]
                             : !bse.has_bars() ? nse.days[nse.next]
                                               : std::min(bse.days[bse.next], nse.days[nse.next]);
    const bool on_bse = bse.trades_on(day);
    const bool on_nse = nse.trades_on(day);
    const Venue venue = state.update(day, on_bse ? bse.turnover[bse.next] : missing,
                                     on_nse ? nse.turnover[nse.next] : missing);
    if (on_bse) {
      bse.out[bse.next++] = venue == Venue::bse ? 1 : 0;
    }
    if (on_nse) {
      nse.out[nse.next++] = venue == Venue::nse ? 1 : 0;
    }
  }
}

}  // namespace

void primary_venue(std::span<const std::int64_t> days, std::span<const double> bse_turnover,
                   std::span<const double> nse_turnover, std::span<Venue> out) {
  require_same_length(days.size(), bse_turnover.size());
  require_same_length(days.size(), nse_turnover.size());
  require_same_length(days.size(), out.size());
  PrimaryVenueState state;
  for (std::size_t index = 0; index < days.size(); ++index) {
    out[index] = state.update(days[index], bse_turnover[index], nse_turnover[index]);
  }
}

void primary_venue(std::span<const std::int64_t> days, std::span<const double> bse_turnover,
                   std::span<const double> nse_turnover, std::span<const std::int64_t> offsets,
                   std::span<Venue> out, unsigned threads) {
  const SeriesBatch batch(bse_turnover, offsets);
  require_same_length(days.size(), bse_turnover.size());
  parallel_for(batch.size(), threads, [&](std::size_t index) {
    primary_venue(batch.slice(days, index), batch.series(index),
                  batch.input_series(nse_turnover, index), batch.slice(out, index));
  });
}

void designated_bars(std::span<const std::int64_t> days, std::span<const double> turnover,
                     std::span<const std::int64_t> offsets, std::span<std::uint8_t> out,
                     unsigned threads) {
  const SeriesBatch batch(turnover, offsets);
  if (batch.size() % 2 != 0) {
    throw InvalidArgument("series come in pairs, BSE then NSE, got " +
                          std::to_string(batch.size()));
  }
  parallel_for(batch.size() / 2, threads, [&](std::size_t instrument) {
    const std::size_t bse = 2 * instrument;
    designate({batch.slice(days, bse), batch.series(bse), batch.slice(out, bse)},
              {batch.slice(days, bse + 1), batch.series(bse + 1), batch.slice(out, bse + 1)});
  });
}

Venue PrimaryVenueState::update(std::int64_t day, double bse_turnover, double nse_turnover) {
  if (started_ && day <= previous_day_) {
    throw InvalidArgument("days must rise, got " + std::to_string(day) + " after " +
                          std::to_string(previous_day_));
  }
  const double bse = traded(bse_turnover);
  const double nse = traded(nse_turnover);
  const std::int64_t month = month_start(day);
  if (!started_) {
    started_ = true;
    is_running_ = true;
    month_ = month;
  } else if (month != month_) {
    month_ = month;
    while (!recent_.empty() && recent_.front().day < month - kWindowDays) {
      recent_.pop_front();
    }
    double window_bse = 0.0;
    double window_nse = 0.0;
    for (const Turnover& held : recent_) {
      window_bse += held.bse;
      window_nse += held.nse;
    }
    is_running_ = window_bse == 0.0 && window_nse == 0.0;
    month_bse_ = 0.0;
    month_nse_ = 0.0;
    venue_ = larger(window_bse, window_nse);
  }
  previous_day_ = day;
  if (is_running_) {
    month_bse_ += bse;
    month_nse_ += nse;
    venue_ = larger(month_bse_, month_nse_);
  }
  recent_.push_back({day, bse, nse});
  return venue_;
}

}  // namespace btcore
