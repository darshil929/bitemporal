#include <gtest/gtest.h>

#include <btcore/venues.hpp>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "series_generators.hpp"

namespace {

using btcore::Venue;

struct Market {
  std::vector<std::int64_t> days;
  std::vector<double> bse;
  std::vector<double> nse;
  std::vector<std::int64_t> offsets{0};
};

// Instruments trading on most weekdays for about two years, one venue sometimes absent, each break
// of 150 days leaving the next month's window without turnover.
Market drawn_market(std::uint64_t seed, double break_chance) {
  btcore::testing::SeriesGenerator draw(seed);
  Market market;
  for (int instrument = 0; instrument < 40; ++instrument) {
    std::int64_t day = 19'000 + static_cast<std::int64_t>(draw.uniform() * 400);
    for (int bar = 0; bar < 500; ++bar) {
      day += draw.uniform() < break_chance ? 150 : (draw.uniform() < 0.2 ? 3 : 1);
      market.days.push_back(day);
      market.bse.push_back(draw.uniform() < 0.1 ? btcore::missing : draw.price());
      market.nse.push_back(draw.uniform() < 0.1 ? btcore::missing : draw.price());
    }
    market.offsets.push_back(static_cast<std::int64_t>(market.days.size()));
  }
  return market;
}

TEST(VenuesProperties, BatchEqualsStreamingAndTheUniverseEachSeriesOnAnyThreadCount) {
  const auto seed = btcore::testing::property_seed();
  const Market market = drawn_market(seed, 0.01);
  std::vector<Venue> alone(market.days.size());
  std::vector<Venue> spread(market.days.size());
  btcore::primary_venue(market.days, market.bse, market.nse, market.offsets, alone, 1);
  btcore::primary_venue(market.days, market.bse, market.nse, market.offsets, spread, 8);
  ASSERT_EQ(alone, spread) << "seed " << seed;
  for (std::size_t series = 0; series + 1 < market.offsets.size(); ++series) {
    btcore::PrimaryVenueState state;
    for (auto row = static_cast<std::size_t>(market.offsets[series]);
         row < static_cast<std::size_t>(market.offsets[series + 1]); ++row) {
      ASSERT_EQ(state.update(market.days[row], market.bse[row], market.nse[row]), alone[row])
          << "seed " << seed << ", series " << series << ", row " << row;
    }
  }
}

// Without breaks every window holds turnover, so within a month after the first every day carries
// the same venue.
TEST(VenuesProperties, HoldsOneVenueThroughEachLaterMonth) {
  const auto seed = btcore::testing::property_seed();
  const Market market = drawn_market(seed + 1, 0.0);
  std::vector<Venue> out(market.days.size());
  btcore::primary_venue(market.days, market.bse, market.nse, market.offsets, out, 0);
  for (std::size_t series = 0; series + 1 < market.offsets.size(); ++series) {
    const auto first = static_cast<std::size_t>(market.offsets[series]);
    const auto last = static_cast<std::size_t>(market.offsets[series + 1]);
    for (std::size_t row = first + 40; row < last; ++row) {
      const std::chrono::year_month_day today{
          std::chrono::sys_days{std::chrono::days{static_cast<int>(market.days[row])}}};
      const std::chrono::year_month_day before{
          std::chrono::sys_days{std::chrono::days{static_cast<int>(market.days[row - 1])}}};
      if (today.month() == before.month() && today.year() == before.year()) {
        ASSERT_EQ(out[row], out[row - 1]) << "seed " << seed << ", row " << row;
      }
    }
  }
}

// The same instruments laid out twice: once by day with both venues' turnover, once as a pair of
// venue series, each bar remembering its day's row and its venue.
struct PairedMarket {
  Market by_day;
  std::vector<std::int64_t> days;
  std::vector<double> turnover;
  std::vector<std::int64_t> offsets{0};
  std::vector<std::size_t> day_row;
  std::vector<Venue> venue;
};

PairedMarket paired_market(std::uint64_t seed) {
  btcore::testing::SeriesGenerator draw(seed);
  PairedMarket market;
  for (int instrument = 0; instrument < 40; ++instrument) {
    std::int64_t day = 19'000 + static_cast<std::int64_t>(draw.uniform() * 400);
    std::vector<std::size_t> bse_rows;
    std::vector<std::size_t> nse_rows;
    for (int bar = 0; bar < 500; ++bar) {
      day += draw.uniform() < 0.01 ? 150 : (draw.uniform() < 0.2 ? 3 : 1);
      const double pick = draw.uniform();
      const std::size_t row = market.by_day.days.size();
      market.by_day.days.push_back(day);
      market.by_day.bse.push_back(pick < 0.75 ? draw.price() : btcore::missing);
      market.by_day.nse.push_back(pick > 0.25 ? draw.price() : btcore::missing);
      if (pick < 0.75) {
        bse_rows.push_back(row);
      }
      if (pick > 0.25) {
        nse_rows.push_back(row);
      }
    }
    market.by_day.offsets.push_back(static_cast<std::int64_t>(market.by_day.days.size()));
    const auto lay_out = [&market](Venue venue, const std::vector<std::size_t>& rows,
                                   const std::vector<double>& turnover) {
      for (const std::size_t row : rows) {
        market.days.push_back(market.by_day.days[row]);
        market.turnover.push_back(turnover[row]);
        market.day_row.push_back(row);
        market.venue.push_back(venue);
      }
      market.offsets.push_back(static_cast<std::int64_t>(market.days.size()));
    };
    lay_out(Venue::bse, bse_rows, market.by_day.bse);
    lay_out(Venue::nse, nse_rows, market.by_day.nse);
  }
  return market;
}

TEST(VenuesProperties, DesignatesTheBarsOfEachDaysPrimaryVenueOnAnyThreadCount) {
  const auto seed = btcore::testing::property_seed();
  const PairedMarket market = paired_market(seed + 2);
  std::vector<std::uint8_t> alone(market.days.size());
  std::vector<std::uint8_t> spread(market.days.size());
  btcore::designated_bars(market.days, market.turnover, market.offsets, alone, 1);
  btcore::designated_bars(market.days, market.turnover, market.offsets, spread, 8);
  ASSERT_EQ(alone, spread) << "seed " << seed;
  const Market& by_day = market.by_day;
  std::vector<Venue> designated(by_day.days.size());
  btcore::primary_venue(by_day.days, by_day.bse, by_day.nse, by_day.offsets, designated, 0);
  for (std::size_t bar = 0; bar < alone.size(); ++bar) {
    ASSERT_EQ(alone[bar], designated[market.day_row[bar]] == market.venue[bar] ? 1 : 0)
        << "seed " << seed << ", bar " << bar;
  }
}

}  // namespace
