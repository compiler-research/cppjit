// The benchmarked API. calls.h includes this once per copy, each time with a
// different BENCH_NS, so that the first-call benchmarks find functions that
// were never called before. No include guard on purpose.
//
// The bodies only hand their input back: the benchmarks measure cppjit's
// call path, not the work the C++ function does.

namespace BENCH_NS {

// Single, non-templated overload: one per primitive type, taken by value,
// pointer, reference and const reference, always returning the value.
#define BENCH_DECLARE_PASS(tag, T)                                             \
  T pass_##tag(T x);                                                           \
  T pass_ptr_##tag(T* x);                                                      \
  T pass_ref_##tag(T& x);                                                      \
  T pass_cref_##tag(const T& x);
BENCH_PRIMITIVES(BENCH_DECLARE_PASS)
#undef BENCH_DECLARE_PASS

std::string pass_string(std::string x);
std::string pass_string_cref(const std::string& x);
std::string_view pass_string_view(std::string_view x);
const char* pass_cstring(const char* x);

// Single, non-templated overload taking several class and enum arguments.
Point pass_point(Point p);
Color pass_color(Color c);
Shape pass_shape(Shape s);
int pass_value_args(Point p, Color c, Shape s);
int pass_ref_args(const Point& p, Widget& w, Shape s);
int pass_ptr_args(Point* p, const Widget* w, Color c);
int pass_mixed_args(const Particle& pa, Widget* w, Point& p, Color c, Shape s);

// One name, several non-templated overloads over classes and enums, mixing
// references and pointers. Each overload returns a different value, so the
// benchmarks can check that resolution picked the intended one.
int overloaded(const Point& p, Color c);
int overloaded(Widget* w, Shape s);
int overloaded(Particle& pa, const Point* p, Color c);
int overloaded(const Widget& w, const Particle& pa, Point* p);
int overloaded(Color c, Shape s);

// Single, templated overload, instantiated with primitive types: deduced
// from the arguments, and given explicitly. Two templates, so that an
// explicit case never finds its instantiation made by a deduced one.
template <typename T> T tmpl_deduce(T x) { return x; }
template <typename T> T tmpl_pass(T x) { return x; }

// Several templated overloads, instantiated with classes and enums.
template <typename T> int tmpl_overloaded(const T&) { return 1; }
template <typename T> int tmpl_overloaded(T*, Color) { return 2; }
template <typename T, typename U> int tmpl_overloaded(const T&, U&, Shape) {
  return 3;
}

// Higher order functions called with a Python callable, overloaded and
// mixing templated and non-templated overloads. Each calls the callback once.
int invoke(int (*cb)(int), int x);
double invoke(double (*cb)(double), double x);
int invoke(int (*cb)(const Point&), const Point& p);
int invoke(const std::function<int(Widget&, Color)>& cb, Widget& w, Color c);
template <typename T> T invoke(T (*cb)(T, T), T x, T y) { return cb(x, y); }

} // namespace BENCH_NS
