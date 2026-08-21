#ifndef MEMORY_ANALYSIS_H
#define MEMORY_ANALYSIS_H

#include <new>
#include <stdlib.h>

class memAnalysisKlass {
  int val;
};
__attribute__((malloc)) memAnalysisKlass* allocTest();
__attribute__((ownership_returns(malloc))) memAnalysisKlass* allocTestReturns();

#endif // MEMORY_ANALYSIS_H