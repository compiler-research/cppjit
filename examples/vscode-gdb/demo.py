"""JIT-compile C++ and call it from Python; debug both in VS Code (see README.md)."""

import os

import cppjit

HERE = os.path.dirname(os.path.abspath(__file__))

# demo.h is user C++ on disk: the JIT compiles it, so breakpoints and steps work in it.
cppjit.add_include_path(HERE)
cppjit.include("demo.h")

# A prebuilt library: its header and the .so (lib/build.sh), but no source.
cppjit.load_library(os.path.join(HERE, "lib", "libhistogram.so"))
cppjit.add_include_path(os.path.join(HERE, "lib"))
cppjit.include("histogram.h")

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


def vector(xs):
    return cppjit.gbl.std.vector["double"](xs)


class Demo:
    def __init__(self, path):
        self.days = cppjit.gbl.demo.load_days(path)
        self.closes = [day.close for day in self.days]

    def report(self):
        stats = cppjit.gbl.summarize(vector(self.closes))
        print("%d days: mean=%.2f max=%.2f" % (len(self.days), stats.mean, stats.max))

    def histogram(self):
        hist = cppjit.gbl.demo.Histogram(min(self.closes), max(self.closes), 5)
        for value in self.closes:
            hist.add(value)
        for i in range(5):
            print("%.2f to %.2f: %s" % (hist.lower(i), hist.upper(i), hist.bar(i)))
        return hist.total()

    def predict(self):
        # Fit each close against the close before it.
        line = cppjit.gbl.demo.fit_line(
            vector(self.closes[:-1]), vector(self.closes[1:])
        )
        print("next close: %.2f (slope %.3f)" % (line.at(self.closes[-1]), line.slope))


if __name__ == "__main__":
    demo = Demo(os.path.join(HERE, "ust10y.json"))
    demo.report()
    print("total", demo.histogram())
    demo.predict()
