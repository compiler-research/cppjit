#ifndef CPPJIT_BENCHMARKS_CALLS_H
#define CPPJIT_BENCHMARKS_CALLS_H

#include <functional>
#include <string>
#include <string_view>

// Argument types shared by every copy of the API, so that the benchmarks can
// build their arguments once, outside the timed region.
struct Point {
  double x = 0., y = 0.;
};

class Widget {
public:
  Widget() = default;
  int id = 0;
};

struct Particle {
  Point position, velocity;
  double mass = 1.;
};

enum Color { Red, Green, Blue };
enum class Shape : int { Circle, Square, Triangle };

// (tag, type) of every primitive type the benchmarks pass across
#define BENCH_PRIMITIVES(X)                                                    \
  X(bool, bool)                                                                \
  X(char, char)                                                                \
  X(schar, signed char)                                                        \
  X(uchar, unsigned char)                                                      \
  X(wchar, wchar_t)                                                            \
  X(char16, char16_t)                                                          \
  X(char32, char32_t)                                                          \
  X(short, short)                                                              \
  X(ushort, unsigned short)                                                    \
  X(int, int)                                                                  \
  X(uint, unsigned int)                                                        \
  X(long, long)                                                                \
  X(ulong, unsigned long)                                                      \
  X(llong, long long)                                                          \
  X(ullong, unsigned long long)                                                \
  X(float, float)                                                              \
  X(double, double)                                                            \
  X(ldouble, long double)

// The copies of the API: `hot` serves the successive-call benchmarks, and the
// first-call benchmarks call `warmup` before they measure `cold`.
#define BENCH_NS hot
#include "calls_api.h"
#undef BENCH_NS

#define BENCH_NS warmup
#include "calls_api.h"
#undef BENCH_NS

#define BENCH_NS cold
#include "calls_api.h"
#undef BENCH_NS

#endif // CPPJIT_BENCHMARKS_CALLS_H
