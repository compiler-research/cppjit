#ifndef MEMORY_ANALYSIS_H
#define MEMORY_ANALYSIS_H

#include <new>
#include <stdlib.h>
namespace memory {

class memAnalysisKlass {
public:
  int val;
};
__attribute__((malloc)) memAnalysisKlass* mallocAttr();
__attribute__((ownership_returns(malloc))) memAnalysisKlass*
ownershipReturnsAttr();
memAnalysisKlass* noAttr();

__attribute__((ownership_takes(malloc, 1))) void
ownershipTakesAttr(memAnalysisKlass* obj);

void takesPtrButNotOwnership(memAnalysisKlass* obj);

struct memOwn {
  int val;
  static int dtorCount;
  memOwn(int value);
  memOwn();
  // Attribute injected by APINotes
  static memOwn* memOwnAllocator(int x) { return new memOwn(x); }
  ~memOwn();
};

// Attribute injected by APINotes
memOwn* memOwnOperatorNew();

// Attribute injected by redeclaration
memOwn* allocDefaultMemOwn();

// No ownership attribute anywhere
memOwn* noAttrAlloc();

[[clang::annotate("cppAllocOperatorNewArr")]]
memOwn* allocOperatorNewArrAttr(size_t size);

[[clang::annotate("cppAllocNewArr")]]
memOwn* allocNewArrAttr(int count);

[[clang::annotate("cppAllocMalloc")]]
memOwn* allocMallocAttr(size_t size);

[[clang::annotate("cppAllocOperatorNew")]]
memOwn* allocOperatorNewAttr();

// A pair of classes that bind_object can cast between. Neither one is
// polymorphic, so the cast needs no runtime type information.
struct memCastBase {
  int base = 0;
};

struct memCastDerived : memCastBase {
  int derived = 0;
};

[[clang::annotate("cppAllocMalloc")]]
memCastDerived* allocMallocDerived();

struct memOwner {

  [[clang::annotate("cppDeallocDelete", 2)]]
  void release(memOwn* obj);

  [[clang::annotate("cppDeallocDelete", 3)]]
  void releaseSecond(memOwn* keep, memOwn* obj);

  [[clang::annotate("cppDeallocDelete", 3)]]
  void releaseAfterCount(int count, memOwn* obj);

  [[clang::annotate("cppDeallocNone", 2)]]
  void keepOwnership(memOwn* obj);

  [[clang::annotate("cppDeallocDelete", 1)]]
  static void releaseStatic(memOwn* obj);

  // One test adds a Python overload to this method, and that overload stays in
  // the shared overload group. The other tests use their own methods, so the
  // added one reaches none of them. Two parameters make a call with a single
  // argument miss this overload, which lets the Python one run.
  [[clang::annotate("cppDeallocDelete", 3)]]
  void releaseOverloaded(memOwn* keep, memOwn* obj);
};

[[clang::annotate("cppDeallocDelete", 2)]]
void releaseFree(memOwner* self, memOwn* obj);

// A raw pointer to a builtin type binds to a LowLevelView, not an instance
[[clang::annotate("cppAllocNewArr")]]
int* allocIntNewArr(int count);

[[clang::annotate("cppAllocOperatorNewArr")]]
int* allocIntOperatorNewArr(size_t count);

[[clang::annotate("cppAllocNew")]]
int* allocIntNew();

[[clang::annotate("cppAllocOperatorNew")]]
int* allocIntOperatorNew();

[[clang::annotate("cppAllocMalloc")]]
int* allocIntMalloc(size_t count);

// No ownership attribute anywhere
int* intNoAttrAlloc();

[[clang::annotate("cppDeallocDeleteArr", 1)]]
void releaseBufferArr(int* buf);

[[clang::annotate("cppDeallocDelete", 1)]]
void releaseBuffer(int* buf);

[[clang::annotate("cppDeallocFree", 1)]]
void releaseBufferMalloc(int* buf);

[[clang::annotate("cppDeallocNone", 1)]]
void keepBuffer(int* buf);

// The analyzer reads function bodies, so these must be inline
inline memOwn* analyzerAllocNew() { return new memOwn; }

inline memOwn* analyzerAllocNewArr() { return new memOwn[5]; }

inline memOwn* analyzerAllocMalloc() { return (memOwn*)malloc(sizeof(memOwn)); }

// A method keeps the first answer it gets, so a test that runs with the
// analyzer off needs a function that no other test calls.
inline memOwn* analyzerOffAllocNew() { return new memOwn; }

inline memOwn* analyzerCachedAllocNew() { return new memOwn; }

struct analyzerOwner {
  void analyzerRelease(memOwn* obj) { delete obj; }

  void analyzerReleaseSecond(memOwn* keep, memOwn* obj) { delete obj; }

  static void analyzerReleaseStatic(memOwn* obj) { delete obj; }

  // the body frees nothing, so the attribute and the analyzer disagree
  [[clang::annotate("cppDeallocDelete", 2)]]
  void analyzerAttrWins(memOwn* obj) {}

  // the attribute answers for keep, and only the analyzer answers for obj
  [[clang::annotate("cppDeallocNone", 2)]]
  void analyzerMixedSlots(memOwn* keep, memOwn* obj) {
    delete obj;
  }

  void analyzerOffRelease(memOwn* obj) { delete obj; }
};

inline void analyzerReleaseFree(memOwn* obj) { delete obj; }

// Defined in memory_analysis.cxx, so the interpreter sees no body of it
void analyzerNoBodyRelease(memOwn* obj);
} // namespace memory
#endif // MEMORY_ANALYSIS_H
