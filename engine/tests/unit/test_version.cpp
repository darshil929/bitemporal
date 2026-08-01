#include <gtest/gtest.h>

#include <btcore/version.hpp>

TEST(Version, IsNotEmpty) { EXPECT_FALSE(btcore::version().empty()); }
