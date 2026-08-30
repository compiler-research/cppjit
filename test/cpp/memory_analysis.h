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
  memOwn(int value) : val(value) {}
  memOwn() { val = 0; }
  // Attribute injected by APINotes
  static memOwn* memOwnAllocator(int x) { return new memOwn(x); }
};

// Attribute injected by APINotes
memOwn* memOwnAllocGlobal();

// Attribute injected by redeclaration
memOwn* allocDefaultMemOwn();

// No ownership attribute anywhere
memOwn* noAttrAlloc();

inline memAnalysisKlass* allocAnalyzerOn() { return new memAnalysisKlass; }
inline memAnalysisKlass* allocAnalyzerOff() { return new memAnalysisKlass; }
} // namespace memory

#endif // MEMORY_ANALYSIS_H
