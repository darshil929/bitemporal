find_package(GTest CONFIG REQUIRED)
find_package(benchmark CONFIG REQUIRED)

add_library(btcore_series_generators STATIC property/series_generators.cpp)
target_include_directories(btcore_series_generators PUBLIC property)
target_link_libraries(btcore_series_generators PRIVATE btcore_warnings)

add_executable(btcore_unit_tests
  property/test_series_generators.cpp
  unit/test_arithmetic.cpp
  unit/test_parallel.cpp
  unit/test_types.cpp
  unit/test_version.cpp
)
target_link_libraries(btcore_unit_tests
  PRIVATE btcore btcore_series_generators btcore_warnings GTest::gtest_main
)

add_executable(btcore_benchmarks bench/bench_parallel.cpp)
target_link_libraries(btcore_benchmarks
  PRIVATE btcore btcore_series_generators btcore_warnings benchmark::benchmark_main
)

include(GoogleTest)
gtest_discover_tests(btcore_unit_tests)
