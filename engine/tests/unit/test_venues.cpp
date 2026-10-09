#include <gtest/gtest.h>

#include <btcore/venues.hpp>
#include <chrono>
#include <cstdint>
#include <limits>
#include <vector>

namespace {

using btcore::Venue;
using std::chrono::sys_days;
using std::chrono::year;

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

std::int64_t on(int y, unsigned m, unsigned d) {
  return sys_days{year{y} / std::chrono::month{m} / std::chrono::day{d}}.time_since_epoch().count();
}

std::vector<Venue> designate(const std::vector<std::int64_t>& days, const std::vector<double>& bse,
                             const std::vector<double>& nse) {
  std::vector<Venue> out(days.size());
  btcore::primary_venue(days, bse, nse, out);
  return out;
}

// In the first month the running totals decide: NSE leads after 10 + 25 against 30 + 0.
TEST(PrimaryVenue, FollowsTheRunningTotalsThroughTheFirstMonth) {
  EXPECT_EQ(designate({on(2024, 3, 4), on(2024, 3, 5), on(2024, 3, 6)}, {30, kNaN, 1}, {10, 25, 1}),
            (std::vector<Venue>{Venue::bse, Venue::nse, Venue::nse}));
}

// April and May read the 90 days to 31 March and 30 April: BSE leads 40 to 30, then NSE 30 + 50.
TEST(PrimaryVenue, ReadsTheNinetyDaysBeforeEachMonth) {
  const auto out = designate({on(2024, 3, 4), on(2024, 4, 1), on(2024, 4, 30), on(2024, 5, 2)},
                             {40, 0, 0, 0}, {30, 0, 50, 0});
  EXPECT_EQ(out[1], Venue::bse);
  EXPECT_EQ(out[2], Venue::bse);
  EXPECT_EQ(out[3], Venue::nse);
}

// February reads the 90 days to 31 January, where both venues traded 7, and a tie goes to BSE.
TEST(PrimaryVenue, GivesBseATie) {
  const auto out = designate({on(2024, 1, 2), on(2024, 2, 1)}, {7, 1}, {7, 9});
  EXPECT_EQ(out[0], Venue::bse);
  EXPECT_EQ(out[1], Venue::bse);
}

// July's window, 2 April to 30 June, holds no turnover, so July follows its running totals as a
// first month does: BSE leads 9 to 2, then NSE 12 to 9.
TEST(PrimaryVenue, FollowsTheRunningTotalsAfterAWindowWithoutTurnover) {
  const auto out =
      designate({on(2024, 1, 2), on(2024, 7, 1), on(2024, 7, 2)}, {5, 9, kNaN}, {7, 2, 10});
  EXPECT_EQ(out[0], Venue::nse);
  EXPECT_EQ(out[1], Venue::bse);
  EXPECT_EQ(out[2], Venue::nse);
}

TEST(PrimaryVenue, RefusesDaysThatDoNotRise) {
  std::vector<Venue> out(2);
  EXPECT_THROW(btcore::primary_venue(std::vector<std::int64_t>{5, 5}, std::vector<double>{1, 1},
                                     std::vector<double>{1, 1}, out),
               btcore::InvalidArgument);
}

}  // namespace
