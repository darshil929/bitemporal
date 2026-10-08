#include <btcore/types.hpp>
#include <string>

namespace btcore {

void require_period(int period) {
  if (period < 1) {
    throw InvalidArgument("period must be at least 1, got " + std::to_string(period));
  }
}

void require_same_length(std::size_t input_length, std::size_t output_length) {
  if (input_length != output_length) {
    throw InvalidArgument("output holds " + std::to_string(output_length) + " values, input " +
                          std::to_string(input_length));
  }
}

SeriesBatch::SeriesBatch(std::span<const double> values, std::span<const std::int64_t> offsets)
    : values_(values), offsets_(offsets) {
  if (offsets.empty()) {
    throw InvalidArgument("offsets must hold at least the leading 0");
  }
  if (offsets.front() != 0) {
    throw InvalidArgument("offsets must begin at 0, got " + std::to_string(offsets.front()));
  }
  for (std::size_t i = 1; i < offsets.size(); ++i) {
    if (offsets[i] < offsets[i - 1]) {
      throw InvalidArgument("offsets decrease at position " + std::to_string(i));
    }
  }
  if (static_cast<std::uint64_t>(offsets.back()) != values.size()) {
    throw InvalidArgument("offsets end at " + std::to_string(offsets.back()) + ", values hold " +
                          std::to_string(values.size()));
  }
}

std::size_t SeriesBatch::start(std::size_t index) const {
  if (index >= size()) {
    throw InvalidArgument("series " + std::to_string(index) + " of " + std::to_string(size()));
  }
  return static_cast<std::size_t>(offsets_[index]);
}

std::span<const double> SeriesBatch::series(std::size_t index) const {
  const std::size_t first = start(index);
  return values_.subspan(first, static_cast<std::size_t>(offsets_[index + 1]) - first);
}

std::span<double> SeriesBatch::series(std::span<double> output, std::size_t index) const {
  require_same_length(values_.size(), output.size());
  const std::size_t first = start(index);
  return output.subspan(first, static_cast<std::size_t>(offsets_[index + 1]) - first);
}

}  // namespace btcore
