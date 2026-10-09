find_package(Python 3.12 REQUIRED COMPONENTS Interpreter Development.Module)
find_package(nanobind CONFIG REQUIRED)

# The static library is linked into a shared module.
set_target_properties(btcore PROPERTIES POSITION_INDEPENDENT_CODE ON)

nanobind_add_module(_btcore STABLE_ABI btcore_py.cpp)
target_link_libraries(_btcore PRIVATE btcore)

nanobind_add_stub(_btcore_stub
  MODULE _btcore
  OUTPUT _btcore.pyi
  PYTHON_PATH $<TARGET_FILE_DIR:_btcore>
  DEPENDS _btcore
  MARKER_FILE py.typed
)

install(TARGETS _btcore LIBRARY DESTINATION btcore)
install(FILES ${CMAKE_CURRENT_BINARY_DIR}/_btcore.pyi ${CMAKE_CURRENT_BINARY_DIR}/py.typed
  DESTINATION btcore)
