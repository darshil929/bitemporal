#include <btcore/version.hpp>

#include <gtest/gtest.h>

TEST(Version, IsNotEmpty) {
  EXPECT_FALSE(btcore::version().empty());
}
