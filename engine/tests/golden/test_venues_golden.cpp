#include <gtest/gtest.h>

#include <btcore/venues.hpp>
#include <charconv>
#include <chrono>
#include <cstdint>
#include <string>
#include <vector>

#include "golden_table.hpp"

namespace {

std::int64_t day_number(const std::string& date) {
  int year = 0;
  unsigned month = 0;
  unsigned day = 0;
  std::from_chars(date.data(), date.data() + 4, year);
  std::from_chars(date.data() + 5, date.data() + 7, month);
  std::from_chars(date.data() + 8, date.data() + 10, day);
  const std::chrono::sys_days point{std::chrono::year{year} / std::chrono::month{month} /
                                    std::chrono::day{day}};
  return point.time_since_epoch().count();
}

TEST(VenuesGolden, PrimaryVenueMatchesTheReference) {
  const auto input = btcore::testing::GoldenTable::read("golden_venue_turnover.csv");
  const auto expected = btcore::testing::GoldenTable::read("golden_primary_venue.csv");
  std::vector<std::int64_t> days;
  for (const auto& date : input.text("trade_date")) {
    days.push_back(day_number(date));
  }
  const auto offsets = input.series_offsets();
  std::vector<btcore::Venue> out(days.size());
  btcore::primary_venue(days, input.numbers("bse_turnover"), input.numbers("nse_turnover"), offsets,
                        out, 0);
  const auto& reference = expected.numbers("primary_venue");
  const auto& series = input.text("series");
  ASSERT_EQ(out.size(), reference.size());
  for (std::size_t row = 0; row < out.size(); ++row) {
    ASSERT_EQ(static_cast<double>(out[row]), reference[row])
        << series[row] << " " << input.text("trade_date")[row];
  }
}

}  // namespace
