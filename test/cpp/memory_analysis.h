#ifndef MEMORY_ANALYSIS_H
#define MEMORY_ANALYSIS_H

#include <new>
#include <stdlib.h>

class memAnalysisKlass {
  int val;
};
__attribute__((malloc)) memAnalysisKlass* allocTest();
__attribute__((ownership_returns(malloc))) memAnalysisKlass* allocTestReturns();

inline memAnalysisKlass* allocNew() { return new memAnalysisKlass; }
inline memAnalysisKlass* allocNew2() { return new memAnalysisKlass; }
#endif // MEMORY_ANALYSIS_H