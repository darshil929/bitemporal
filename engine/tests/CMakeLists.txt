find_package(GTest CONFIG REQUIRED)

add_executable(btcore_unit_tests unit/test_arithmetic.cpp unit/test_version.cpp)
target_link_libraries(btcore_unit_tests PRIVATE btcore btcore_warnings GTest::gtest_main)

include(GoogleTest)
gtest_discover_tests(btcore_unit_tests)
