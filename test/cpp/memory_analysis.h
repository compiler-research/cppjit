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
} // namespace memory

#endif // MEMORY_ANALYSIS_H
