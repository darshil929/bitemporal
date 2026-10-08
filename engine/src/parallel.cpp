#include <algorithm>
#include <atomic>
#include <btcore/parallel.hpp>
#include <exception>
#include <mutex>
#include <thread>
#include <vector>

namespace btcore {

namespace {

// Several chunks per thread even out series of uneven length; a cap keeps the counter from being
// read once per index on a large count.
constexpr std::size_t kChunksPerThread = 16;
constexpr std::size_t kLargestChunk = 256;

unsigned thread_count(std::size_t count, unsigned requested) {
  const unsigned available = requested != 0 ? requested : std::thread::hardware_concurrency();
  const std::size_t useful = std::min<std::size_t>(std::max(available, 1U), count);
  return static_cast<unsigned>(useful);
}

}  // namespace

void parallel_for(std::size_t count, unsigned threads,
                  const std::function<void(std::size_t)>& work) {
  if (count == 0) {
    return;
  }
  const unsigned workers = thread_count(count, threads);
  if (workers == 1) {
    for (std::size_t index = 0; index < count; ++index) {
      work(index);
    }
    return;
  }

  const std::size_t chunk =
      std::clamp<std::size_t>(count / (workers * kChunksPerThread), 1, kLargestChunk);
  std::atomic<std::size_t> next{0};
  std::atomic<bool> stopped{false};
  std::mutex failure_guard;
  std::exception_ptr failure;

  auto drain = [&] {
    while (!stopped.load(std::memory_order_relaxed)) {
      const std::size_t first = next.fetch_add(chunk, std::memory_order_relaxed);
      if (first >= count) {
        return;
      }
      const std::size_t last = std::min(count, first + chunk);
      try {
        for (std::size_t index = first; index < last; ++index) {
          work(index);
        }
      } catch (...) {
        // Carried to the calling thread, which raises it after every worker has stopped.
        const std::lock_guard lock(failure_guard);
        if (!failure) {
          failure = std::current_exception();
        }
        stopped.store(true, std::memory_order_relaxed);
      }
    }
  };

  {
    std::vector<std::jthread> pool;
    pool.reserve(workers - 1);
    for (unsigned helper = 1; helper < workers; ++helper) {
      pool.emplace_back(drain);
    }
    drain();
  }
  if (failure) {
    std::rethrow_exception(failure);
  }
}

}  // namespace btcore
