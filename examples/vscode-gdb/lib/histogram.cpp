#include "histogram.h"

namespace demo {

Histogram::Histogram(double lo, double hi, std::size_t buckets)
    : lo_(lo), hi_(hi), counts_(buckets, 0) {}

void Histogram::add(double x) {
  std::size_t i = index(x);
  counts_[i] += 1;
  total_ += 1;
}

std::size_t Histogram::count(std::size_t i) const { return counts_.at(i); }
double Histogram::lower(std::size_t i) const { return lo_ + i * width(); }
double Histogram::upper(std::size_t i) const { return lower(i + 1); }
std::size_t Histogram::total() const { return total_; }

std::string Histogram::bar(std::size_t i, char mark) const {
  return std::string(counts_.at(i), mark);
}

double Histogram::width() const { return (hi_ - lo_) / counts_.size(); }

std::size_t Histogram::index(double x) const {
  long i = static_cast<long>((x - lo_) / width());
  if (i < 0)
    i = 0;
  if (i >= static_cast<long>(counts_.size()))
    i = static_cast<long>(counts_.size()) - 1;
  return static_cast<std::size_t>(i);
}

} // namespace demo
