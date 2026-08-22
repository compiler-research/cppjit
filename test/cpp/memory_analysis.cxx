#include "memory_analysis.h"
__attribute__((malloc)) memAnalysisKlass* allocTest() {
  return new memAnalysisKlass;
}

__attribute__((ownership_returns(malloc))) memAnalysisKlass*
allocTestReturns() {
  return new memAnalysisKlass;
}