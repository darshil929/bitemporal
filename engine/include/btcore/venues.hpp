#pragma once

#include <btcore/types.hpp>
#include <cstdint>
#include <deque>
#include <span>

namespace btcore {

/// The venues an instrument trades on, BSE first since a tie goes to it.
enum class Venue : std::int8_t { bse = 0, nse = 1 };

/// The primary venue of each day. A month's venue is the one with the larger turnover
/// over the 90 calendar days ending on the last day of the month before. In the series' first
/// month, and in a month whose 90 days hold no turnover at either venue, it is the one with the
/// larger turnover from the month's first day through the day. A tie goes to BSE. `days` count
/// calendar days from 1970-01-01, rise strictly and hold every day either venue traded; a venue's
/// turnover is missing on a day it did not trade.
void primary_venue(std::span<const std::int64_t> days, std::span<const double> bse_turnover,
                   std::span<const double> nse_turnover, std::span<Venue> out);

/// The batch form over every series the offsets mark in the three inputs, across threads.
void primary_venue(std::span<const std::int64_t> days, std::span<const double> bse_turnover,
                   std::span<const double> nse_turnover, std::span<const std::int64_t> offsets,
                   std::span<Venue> out, unsigned threads);

/// 1 for each bar on its instrument's primary venue that day, 0 for a bar on the other. The series
/// come in pairs, instrument `i`'s BSE bars in series `2i` and its NSE bars in series `2i + 1`,
/// either empty where it never traded there; `days` and `turnover` are laid out like the bars, and
/// each series' days rise strictly. A day the designated venue did not trade has no designated bar.
void designated_bars(std::span<const std::int64_t> days, std::span<const double> turnover,
                     std::span<const std::int64_t> offsets, std::span<std::uint8_t> out,
                     unsigned threads);

/// The primary venue one day at a time, equal to the batch form.
class PrimaryVenueState {
 public:
  [[nodiscard]] Venue update(std::int64_t day, double bse_turnover, double nse_turnover);

 private:
  struct Turnover {
    std::int64_t day;
    double bse;
    double nse;
  };

  bool started_ = false;
  bool is_running_ = false;
  std::int64_t month_ = 0;
  std::int64_t previous_day_ = 0;
  double month_bse_ = 0.0;
  double month_nse_ = 0.0;
  Venue venue_ = Venue::bse;
  std::deque<Turnover> recent_;
};

}  // namespace btcore
