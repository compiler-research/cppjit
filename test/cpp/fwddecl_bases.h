#ifndef CPPJIT_TEST_FWDDECL_BASES_H
#define CPPJIT_TEST_FWDDECL_BASES_H

namespace FwdDeclBases {
struct Base {
  int f() const { return 42; }
};
struct Derived : Base {};
} // namespace FwdDeclBases

#endif // CPPJIT_TEST_FWDDECL_BASES_H
