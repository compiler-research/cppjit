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

__attribute__((ownership_takes(malloc, 1))) void
ownershipTakesAttr(memAnalysisKlass* obj) {
  free(obj);
}

void takesPtrButNotOwnership(memAnalysisKlass* obj) {
  // Does something with obj but does not take/holds its ownership
  return;
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

memCastDerived* allocMallocDerived() {
  return (memCastDerived*)malloc(sizeof(memCastDerived));
}

void memOwner::release(memOwn* obj) { delete obj; }

void memOwner::releaseSecond(memOwn* keep, memOwn* obj) { delete obj; }

void memOwner::releaseAfterCount(int count, memOwn* obj) { delete obj; }

void memOwner::keepOwnership(memOwn* obj) { return; }

void memOwner::releaseStatic(memOwn* obj) { delete obj; }

void memOwner::releaseOverloaded(memOwn* keep, memOwn* obj) { delete obj; }

void releaseFree(memOwner* self, memOwn* obj) { delete obj; }

int* allocIntNewArr(int count) { return new int[count]; }

int* allocIntOperatorNewArr(size_t count) {
  return (int*)::operator new[](count * sizeof(int));
}

int* allocIntNew() { return new int; }

int* allocIntOperatorNew() { return (int*)::operator new(sizeof(int)); }

int* allocIntMalloc(size_t count) { return (int*)malloc(count * sizeof(int)); }

int* intNoAttrAlloc() { return new int[5]; }

void releaseBufferArr(int* buf) { delete[] buf; }

void releaseBuffer(int* buf) { delete buf; }

void releaseBufferMalloc(int* buf) { free(buf); }

void keepBuffer(int* buf) { return; }

void analyzerNoBodyRelease(memOwn* obj) { delete obj; }

} // namespace memory
