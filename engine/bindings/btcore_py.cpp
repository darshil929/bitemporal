#include <btcore/version.hpp>

#include <nanobind/nanobind.h>
#include <nanobind/stl/string_view.h>

namespace nb = nanobind;

NB_MODULE(_btcore, m) {
  m.def("version", &btcore::version);
}
