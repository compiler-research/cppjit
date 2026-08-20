"""Wheel smoke test, run from a clean venv by cibuildwheel's test step:
libcppjit.so must locate libclangCppInterOp relative to its own path (the
build tree is gone by test time), and the template instantiation plus the
header check prove the shipped include tree."""

import os

import cppjit
import cppjit_backend

cppjit.cppdef("int wheel_smoke(int x) { return x + 1; }")
assert cppjit.gbl.wheel_smoke(41) == 42

v = cppjit.gbl.std.vector["int"]()
v.push_back(7)
assert v[0] == 7

api = os.path.join(
    os.path.dirname(cppjit_backend.__file__), "include", "cpyrt", "API.h"
)
assert os.path.exists(api), api

print("wheel smoke OK")
