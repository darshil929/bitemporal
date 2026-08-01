cmake_minimum_required(VERSION 3.24)
project(btcore VERSION 0.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

option(BTCORE_BUILD_TESTS "Build the test suite" ON)
option(BTCORE_BUILD_PYTHON "Build the nanobind module" OFF)
set(BTCORE_SANITIZER "" CACHE STRING "Sanitizer to enable: address, undefined or thread")

if(BTCORE_SANITIZER)
  add_compile_options(-fsanitize=${BTCORE_SANITIZER} -fno-omit-frame-pointer -g)
  add_link_options(-fsanitize=${BTCORE_SANITIZER})
endif()

# libc++ names its hardened mode differently from libstdc++, which uses _GLIBCXX_ASSERTIONS.
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_definitions(_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_EXTENSIVE)
endif()

add_library(btcore src/version.cpp)
target_include_directories(btcore PUBLIC $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_definitions(btcore PRIVATE BTCORE_VERSION="${PROJECT_VERSION}")
target_compile_options(btcore PRIVATE -Wall -Wextra -Wpedantic -Werror)

if(BTCORE_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()

if(BTCORE_BUILD_PYTHON)
  add_subdirectory(bindings)
endif()
