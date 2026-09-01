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

inline memAnalysisKlass* allocAnalyzerOn() { return new memAnalysisKlass; }
inline memAnalysisKlass* allocAnalyzerOff() { return new memAnalysisKlass; }
inline memOwn* allocOperatorNewArr(size_t size) {
  return (memOwn*)::operator new[](sizeof(memOwn) * size);
}
inline memOwn* allocNewArr(int count) { return new memOwn[count]; }
inline memOwn* allocMalloc(size_t size) {
  return (memOwn*)malloc(sizeof(memOwn) * size);
}
inline memOwn* allocOperatorNew() {
  return (memOwn*)::operator new(sizeof(memOwn));
}
[[clang::annotate("cppAllocOperatorNewArr")]]
memOwn* allocOperatorNewArrAttr(size_t size);

[[clang::annotate("cppAllocNewArr")]]
memOwn* allocNewArrAttr(int count);

[[clang::annotate("cppAllocMalloc")]]
memOwn* allocMallocAttr(size_t size);

[[clang::annotate("cppAllocOperatorNew")]]
memOwn* allocOperatorNewAttr();
} // namespace memory

#endif // MEMORY_ANALYSIS_H
