#include "memory_analysis.h"

namespace memory {

__attribute__((malloc)) memAnalysisKlass* mallocAttr() {
  return new memAnalysisKlass;
}

__attribute__((ownership_returns(malloc))) memAnalysisKlass*
ownershipReturnsAttr() {
  return new memAnalysisKlass;
}

// Expected to not return ownership when analysis is off, and there is just
// attr-check
memAnalysisKlass* noAttr() { return new memAnalysisKlass; }

memOwn* memOwnAllocGlobal() { return (memOwn*)malloc(sizeof(memOwn)); }

memOwn* allocDefaultMemOwn() { return new memOwn; }

memOwn* noAttrAlloc() { return new memOwn; }

} // namespace memory
