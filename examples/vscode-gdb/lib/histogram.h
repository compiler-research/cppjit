// A prebuilt library: demo.py loads libhistogram.so and includes this header.
// The JIT sees only the declarations, so gdb shows the source of the
// implementation only if it can find histogram.cpp (see build.sh).
#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace demo {

// Counts values into equal-width buckets between lo and hi.
class Histogram {
public:
  Histogram(double lo, double hi, std::size_t buckets);

  void add(double x);

  std::size_t count(std::size_t i) const;
  double lower(std::size_t i) const;
  double upper(std::size_t i) const;
  std::size_t total() const;

  std::string bar(std::size_t i, char mark = '#') const;

private:
  double width() const;
  std::size_t index(double x) const;

  double lo_;
  double hi_;
  std::vector<std::size_t> counts_;
  std::size_t total_ = 0;
};

} // namespace demo
