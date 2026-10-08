#pragma once

#include <cstddef>
#include <functional>

namespace btcore {

/// Calls `work(index)` once for every index in [0, count), spread over up to `threads` threads, the
/// calling thread among them; 0 means one per hardware thread. Indices are handed out in chunks
/// from a shared counter, so the order of calls is not fixed and `work` writes only what its index
/// owns. The first exception `work` raises stops further chunks and is raised again on the calling
/// thread once every thread has finished.
void parallel_for(std::size_t count, unsigned threads,
                  const std::function<void(std::size_t)>& work);

}  // namespace btcore
