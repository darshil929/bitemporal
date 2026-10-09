cmake_minimum_required(VERSION 3.24)
project(btcore VERSION 0.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BTCORE_BUILD_TESTS "Build the test suite" ON)
option(BTCORE_BUILD_PYTHON "Build the nanobind module" OFF)
set(BTCORE_SANITIZER "" CACHE STRING "Sanitizer to enable: address, undefined or thread")

find_program(BTCORE_CCACHE ccache)
if(BTCORE_CCACHE AND NOT CMAKE_CXX_COMPILER_LAUNCHER)
  set(CMAKE_CXX_COMPILER_LAUNCHER ${BTCORE_CCACHE})
endif()

if(BTCORE_SANITIZER)
  add_compile_options(-fsanitize=${BTCORE_SANITIZER} -fno-omit-frame-pointer -g)
  add_link_options(-fsanitize=${BTCORE_SANITIZER})
endif()

# Left to itself a compiler fuses a * b + c into a single rounding wherever it chooses, and clang
# and GCC choose differently. A fused multiply-add happens only where the code calls std::fma.
add_compile_options(-ffp-contract=off)

# libc++ and libstdc++ each read their own hardening macro and ignore the other's.
add_compile_definitions(
  _LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE
  _GLIBCXX_ASSERTIONS
)

# Warnings for the engine's own sources, which code built against the library does not inherit.
add_library(btcore_warnings INTERFACE)
target_compile_options(btcore_warnings INTERFACE
  -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow -Wdouble-promotion -Werror
)

find_package(Threads REQUIRED)

add_library(btcore
  src/indicators/moving_average.cpp
  src/indicators/price_bands.cpp
  src/indicators/range_extremes.cpp
  src/indicators/relative_strength.cpp
  src/indicators/returns.cpp
  src/indicators/variance.cpp
  src/indicators/volatility.cpp
  src/maths/log1p.cpp
  src/parallel.cpp
  src/types.cpp
  src/version.cpp
)
target_include_directories(btcore PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_definitions(btcore PRIVATE BTCORE_VERSION="${PROJECT_VERSION}")
target_link_libraries(btcore PUBLIC Threads::Threads PRIVATE btcore_warnings)

if(BTCORE_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()

if(BTCORE_BUILD_PYTHON)
  add_subdirectory(bindings)
endif()
