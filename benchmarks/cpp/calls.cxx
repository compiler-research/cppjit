#include "calls.h"

// Markers for counting instructions under callgrind (see ../callgrind.sh),
// called through ctypes so that cppjit's own call path stays out of them.
// Without the valgrind headers they do nothing, and bench_on_valgrind()
// says so.
#if __has_include(<valgrind/callgrind.h>)
#include <valgrind/callgrind.h>

extern "C" int bench_on_valgrind() { return RUNNING_ON_VALGRIND ? 1 : 0; }
extern "C" void bench_toggle_collect() { CALLGRIND_TOGGLE_COLLECT; }
extern "C" void bench_dump(const char* name) { CALLGRIND_DUMP_STATS_AT(name); }
#else
extern "C" int bench_on_valgrind() { return -1; }
extern "C" void bench_toggle_collect() {}
extern "C" void bench_dump(const char*) {}
#endif

#define BENCH_NS hot
#include "calls_api_impl.h"
#undef BENCH_NS

#define BENCH_NS warmup
#include "calls_api_impl.h"
#undef BENCH_NS

#define BENCH_NS cold
#include "calls_api_impl.h"
#undef BENCH_NS
