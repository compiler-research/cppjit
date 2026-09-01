#include "memory_analysis.h"

namespace memory {

int memOwn::dtorCount = 0;

memOwn::memOwn(int value) : val(value) {}

memOwn::memOwn() { val = 0; }

memOwn::~memOwn() { ++dtorCount; }

__attribute__((malloc)) memAnalysisKlass* mallocAttr() {
  return (memAnalysisKlass*)malloc(sizeof(memAnalysisKlass));
}

__attribute__((ownership_returns(malloc))) memAnalysisKlass*
ownershipReturnsAttr() {
  return (memAnalysisKlass*)malloc(sizeof(memAnalysisKlass));
}

// Expected to not return ownership when analysis is off, and there is just
// attr-check
memAnalysisKlass* noAttr() { return new memAnalysisKlass; }

memOwn* memOwnOperatorNew() { return (memOwn*)::operator new(sizeof(memOwn)); }

memOwn* allocDefaultMemOwn() { return new memOwn; }

memOwn* noAttrAlloc() { return new memOwn; }

memOwn* allocOperatorNewArrAttr(size_t size) {
  return (memOwn*)::operator new[](sizeof(memOwn) * size);
}

memOwn* allocNewArrAttr(int count) { return new memOwn[count]; }

memOwn* allocMallocAttr(size_t size) {
  return (memOwn*)malloc(sizeof(memOwn) * size);
}

memOwn* allocOperatorNewAttr() {
  return (memOwn*)::operator new(sizeof(memOwn));
}
} // namespace memory
