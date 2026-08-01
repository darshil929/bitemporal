#include <btcore/version.hpp>

namespace btcore {

std::string_view version() noexcept {
  return BTCORE_VERSION;
}

}  // namespace btcore
