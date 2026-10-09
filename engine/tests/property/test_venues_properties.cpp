#include <gtest/gtest.h>

#include <btcore/venues.hpp>
#include <chrono>
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

}  // namespace
