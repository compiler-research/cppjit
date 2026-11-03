// User C++ that demo.py loads with cppjit.include: a breakpoint in this file
// binds, and a step goes through it, because the JIT compiles it from disk.
#pragma once

#include <cstddef>
#include <fstream>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

namespace demo {

// One day's closing value, as in ust10y.json.
struct Day {
  std::string date;
  double close;
};
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE(Day, date, close)

inline std::vector<Day> load_days(const std::string& path) {
  std::ifstream in(path);
  return nlohmann::json::parse(in).get<std::vector<Day>>();
}

// The least-squares line y = intercept + slope * x.
struct Line {
  double intercept;
  double slope;
  double at(double x) const { return intercept + slope * x; }
};

inline Line fit_line(const std::vector<double>& xs,
                     const std::vector<double>& ys) {
  double n = xs.size(), sx = 0, sy = 0, sxx = 0, sxy = 0;
  for (std::size_t i = 0; i < xs.size(); ++i) {
    sx += xs[i];
    sy += ys[i];
    sxx += xs[i] * xs[i];
    sxy += xs[i] * ys[i];
  }
  double slope = (n * sxy - sx * sy) / (n * sxx - sx * sx);
  return {(sy - slope * sx) / n, slope};
}

} // namespace demo
