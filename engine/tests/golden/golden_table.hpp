#pragma once

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace btcore::testing {

/// One CSV file of the golden data, read whole. The series, isin, venue and trade_date columns keep
/// their text; every other column is read as numbers, an empty field as a missing value.
class GoldenTable {
 public:
  /// Reads `file` from the golden data folder. Throws std::runtime_error when the file cannot be
  /// read, a row's field count differs from the header's, or a number does not parse whole.
  [[nodiscard]] static GoldenTable read(const std::string& file);

  [[nodiscard]] std::size_t rows() const noexcept { return rows_; }

  /// Throws std::out_of_range when the table holds no such column.
  [[nodiscard]] const std::vector<std::string>& text(const std::string& column) const;
  [[nodiscard]] const std::vector<double>& numbers(const std::string& column) const;

  /// The series in file order, and the offsets marking where each begins and the last ends.
  [[nodiscard]] std::vector<std::string> series_names() const;
  [[nodiscard]] std::vector<std::int64_t> series_offsets() const;

 private:
  std::size_t rows_ = 0;
  std::map<std::string, std::vector<std::string>> text_;
  std::map<std::string, std::vector<double>> numbers_;
};

}  // namespace btcore::testing
