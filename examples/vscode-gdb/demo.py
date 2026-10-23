"""JIT-compile C++ and call it from Python; debug both in VS Code (see README.md)."""

import os

import cppjit

# demo.h is user C++ on disk: the JIT compiles it, so breakpoints and steps work in it.
cppjit.add_include_path(os.path.dirname(os.path.abspath(__file__)))
cppjit.include("demo.h")

cppjit.cppdef(r"""
#include <vector>

struct Stats {
  double mean;
  double max;
};

Stats summarize(const std::vector<double>& xs) {
  Stats stats{0.0, xs.empty() ? 0.0 : xs[0]};
  for (double x : xs) {
    stats.mean += x;
    if (x > stats.max)
      stats.max = x;
  }
  if (!xs.empty())
    stats.mean /= xs.size();
  return stats;
}
""")


def report(values):
    stats = cppjit.gbl.summarize(cppjit.gbl.std.vector["double"](values))
    print("mean=%.2f max=%.2f" % (stats.mean, stats.max))


def histogram(values):
    hist = cppjit.gbl.demo.Histogram(0.0, 6.0, 3)
    for value in values:
        hist.add(value)
    for i in range(3):
        print("bucket %d: %s" % (i, hist.bar(i)))
    return hist.total()


if __name__ == "__main__":
    values = [3.0, 1.5, 4.0, 1.0, 5.5]
    report(values)
    print("total", histogram(values))
