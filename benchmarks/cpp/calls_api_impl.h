// Definitions for calls_api.h, included by calls.cxx once per BENCH_NS copy.
// No include guard on purpose.

namespace BENCH_NS {

#define BENCH_DEFINE_PASS(tag, T)                                              \
  T pass_##tag(T x) { return x; }                                              \
  T pass_ptr_##tag(T* x) { return *x; }                                        \
  T pass_ref_##tag(T& x) { return x; }                                         \
  T pass_cref_##tag(const T& x) { return x; }
BENCH_PRIMITIVES(BENCH_DEFINE_PASS)
#undef BENCH_DEFINE_PASS

std::string pass_string(std::string x) { return x; }
std::string pass_string_cref(const std::string& x) { return x; }
std::string_view pass_string_view(std::string_view x) { return x; }
const char* pass_cstring(const char* x) { return x; }

Point pass_point(Point p) { return p; }
Color pass_color(Color c) { return c; }
Shape pass_shape(Shape s) { return s; }
int pass_value_args(Point, Color, Shape) { return 0; }
int pass_ref_args(const Point&, Widget&, Shape) { return 0; }
int pass_ptr_args(Point*, const Widget*, Color) { return 0; }
int pass_mixed_args(const Particle&, Widget*, Point&, Color, Shape) {
  return 0;
}

int overloaded(const Point&, Color) { return 1; }
int overloaded(Widget*, Shape) { return 2; }
int overloaded(Particle&, const Point*, Color) { return 3; }
int overloaded(const Widget&, const Particle&, Point*) { return 4; }
int overloaded(Color, Shape) { return 5; }

int invoke(int (*cb)(int), int x) { return cb(x); }
double invoke(double (*cb)(double), double x) { return cb(x); }
int invoke(int (*cb)(const Point&), const Point& p) { return cb(p); }
int invoke(const std::function<int(Widget&, Color)>& cb, Widget& w, Color c) {
  return cb(w, c);
}

} // namespace BENCH_NS
