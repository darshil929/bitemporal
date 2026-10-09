find_package(GTest CONFIG REQUIRED)
find_package(benchmark CONFIG REQUIRED)

add_library(btcore_series_generators STATIC property/series_generators.cpp)
target_include_directories(btcore_series_generators PUBLIC property)
target_link_libraries(btcore_series_generators PRIVATE btcore_warnings)

# The golden data: real adjusted series, and the values each computation must reproduce from them.
add_library(btcore_golden_table STATIC golden/golden_table.cpp)
target_include_directories(btcore_golden_table PUBLIC golden)
target_compile_definitions(btcore_golden_table PRIVATE BTCORE_GOLDEN_DIR="${CMAKE_CURRENT_SOURCE_DIR}/golden")
target_link_libraries(btcore_golden_table PRIVATE btcore_warnings)

add_executable(btcore_unit_tests
  golden/test_golden_table.cpp
  golden/test_moving_average_golden.cpp
  golden/test_price_bands_golden.cpp
  golden/test_relative_strength_golden.cpp
  golden/test_returns_golden.cpp
  golden/test_variance_golden.cpp
  property/test_moving_average_properties.cpp
  property/test_price_bands_properties.cpp
  property/test_relative_strength_properties.cpp
  property/test_returns_properties.cpp
  property/test_series_generators.cpp
  property/test_variance_properties.cpp
  unit/test_arithmetic.cpp
  unit/test_moving_average.cpp
  unit/test_parallel.cpp
  unit/test_price_bands.cpp
  unit/test_relative_strength.cpp
  unit/test_returns.cpp
  unit/test_types.cpp
  unit/test_variance.cpp
  unit/test_version.cpp
)
target_link_libraries(btcore_unit_tests
  PRIVATE btcore btcore_golden_table btcore_series_generators btcore_warnings GTest::gtest_main
)

add_executable(btcore_benchmarks
  bench/bench_moving_average.cpp
  bench/bench_parallel.cpp
  bench/bench_price_bands.cpp
  bench/bench_relative_strength.cpp
  bench/bench_returns.cpp
  bench/bench_variance.cpp
)
target_link_libraries(btcore_benchmarks
  PRIVATE btcore btcore_series_generators btcore_warnings benchmark::benchmark_main
)

include(GoogleTest)
gtest_discover_tests(btcore_unit_tests)
