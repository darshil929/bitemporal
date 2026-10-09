#include "golden_table.hpp"

#include <charconv>
#include <fstream>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <system_error>

namespace btcore::testing {

namespace {

const std::set<std::string> kTextColumns{"series", "isin", "venue", "trade_date"};

std::vector<std::string> split(const std::string& line) {
  std::vector<std::string> fields;
  std::stringstream stream(line);
  std::string field;
  while (std::getline(stream, field, ',')) {
    fields.push_back(field);
  }
  if (!line.empty() && line.back() == ',') {
    fields.emplace_back();
  }
  return fields;
}

double parse(const std::string& field, const std::string& file, std::size_t row) {
  if (field.empty()) {
    return std::numeric_limits<double>::quiet_NaN();
  }
  double value = 0.0;
  const char* end = field.data() + field.size();
  const auto [stop, error] = std::from_chars(field.data(), end, value);
  if (error != std::errc{} || stop != end) {
    throw std::runtime_error(file + " row " + std::to_string(row) + ": '" + field +
                             "' is not a number");
  }
  return value;
}

}  // namespace

GoldenTable GoldenTable::read(const std::string& file) {
  std::ifstream input(std::string(BTCORE_GOLDEN_DIR) + "/" + file);
  if (!input) {
    throw std::runtime_error("cannot read " + file);
  }
  std::string line;
  std::getline(input, line);
  const auto header = split(line);

  GoldenTable table;
  while (std::getline(input, line)) {
    const auto fields = split(line);
    if (fields.size() != header.size()) {
      throw std::runtime_error(file + " row " + std::to_string(table.rows_ + 1) + " holds " +
                               std::to_string(fields.size()) + " fields, the header " +
                               std::to_string(header.size()));
    }
    for (std::size_t index = 0; index < header.size(); ++index) {
      if (kTextColumns.contains(header[index])) {
        table.text_[header[index]].push_back(fields[index]);
      } else {
        table.numbers_[header[index]].push_back(parse(fields[index], file, table.rows_ + 1));
      }
    }
    ++table.rows_;
  }
  return table;
}

const std::vector<std::string>& GoldenTable::text(const std::string& column) const {
  return text_.at(column);
}

const std::vector<double>& GoldenTable::numbers(const std::string& column) const {
  return numbers_.at(column);
}

std::vector<std::string> GoldenTable::series_names() const {
  std::vector<std::string> names;
  for (const auto& name : text("series")) {
    if (names.empty() || names.back() != name) {
      names.push_back(name);
    }
  }
  return names;
}

std::vector<std::int64_t> GoldenTable::series_offsets() const {
  const auto& series = text("series");
  std::vector<std::int64_t> offsets{0};
  for (std::size_t row = 1; row < series.size(); ++row) {
    if (series[row] != series[row - 1]) {
      offsets.push_back(static_cast<std::int64_t>(row));
    }
  }
  if (!series.empty()) {
    offsets.push_back(static_cast<std::int64_t>(series.size()));
  }
  return offsets;
}

}  // namespace btcore::testing
