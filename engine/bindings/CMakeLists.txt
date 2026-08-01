find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(nanobind CONFIG REQUIRED)

nanobind_add_module(_btcore STABLE_ABI btcore_py.cpp)
target_link_libraries(_btcore PRIVATE btcore)

install(TARGETS _btcore LIBRARY DESTINATION btcore)
