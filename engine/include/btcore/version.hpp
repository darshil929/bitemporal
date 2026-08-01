#pragma once

#include <string_view>

namespace btcore {

/// Version of the compiled library.
[[nodiscard]] std::string_view version() noexcept;

}  // namespace btcore
