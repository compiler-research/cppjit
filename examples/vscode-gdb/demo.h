// User C++ that demo.py loads with cppjit.include: a breakpoint in this file
// binds, and a step goes through it, because the JIT compiles it from disk.
#pragma once

#include <cstddef>
#include <string>
#include <vector>

namespace demo {

// Counts values into equal-width buckets between lo and hi.
class Histogram {
public:
  Histogram(double lo, double hi, std::size_t buckets)
      : lo_(lo), hi_(hi), counts_(buckets, 0) {}

  void add(double x) {
    std::size_t i = index(x);
    counts_[i] += 1;
    total_ += 1;
  }

  std::size_t count(std::size_t i) const { return counts_.at(i); }
  std::size_t total() const { return total_; }

  std::string bar(std::size_t i, char mark = '#') const {
    return std::string(counts_.at(i), mark);
  }

private:
  std::size_t index(double x) const {
    double width = (hi_ - lo_) / counts_.size();
    long i = static_cast<long>((x - lo_) / width);
    if (i < 0)
      i = 0;
    if (i >= static_cast<long>(counts_.size()))
      i = static_cast<long>(counts_.size()) - 1;
    return static_cast<std::size_t>(i);
  }

  double lo_;
  double hi_;
  std::vector<std::size_t> counts_;
  std::size_t total_ = 0;
};

} // namespace demo
