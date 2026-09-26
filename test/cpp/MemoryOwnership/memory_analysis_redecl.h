#ifndef MEMORY_ANALYSIS_REDECL_H
#define MEMORY_ANALYSIS_REDECL_H
#include "../memory_analysis.h"

namespace memory {
[[clang::annotate("cppAllocNew")]]
memOwn* allocDefaultMemOwn();
}

#endif
