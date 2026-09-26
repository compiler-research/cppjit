import gc
import os
import subprocess
import sys

import py
from pytest import mark
from support import IS_CLANG_LT_22, IS_CLING, IS_MAC, setup_make

currpath = py.path.local(__file__).dirpath()
test_dct = str(currpath.join("cpp/memory_analysisDict"))

FLAGS = "-fmodules -fimplicit-module-maps -fapinotes-modules"
IN_CHILD = "-fapinotes-modules" in os.getenv("CPPINTEROP_EXTRA_INTERPRETER_ARGS", "")


def setup_module(mod):
    setup_make("memory_analysis")


# LLVM 21 cannot JIT inline functions when modules is enabled.
# On macOS libc++'s own headers come in as a module under FLAGS, so
# apinotes/modules test cause failure in LLVM 21-macOS because an
# inline libc++ function is called with cppjit.load_library(...) line
@mark.skipif(
    IS_CLANG_LT_22 and IS_MAC,
    reason="LLVM < 22 does not emit inline definitions that come from a module",
)
@mark.skipif(
    IN_CHILD or IS_CLING,
    reason="Cling asserts in collectModuleMaps when built with " + FLAGS,
)
def test00_driver():
    env = os.environ.copy()
    env["CPPINTEROP_EXTRA_INTERPRETER_ARGS"] = (
        env.get("CPPINTEROP_EXTRA_INTERPRETER_ARGS", "") + " " + FLAGS
    )
    subprocess.check_call([sys.executable, "-m", "pytest", __file__], env=env)


class TestMEMORYANALYSIS:
    def setup_class(cls):
        cls.test_dct = test_dct
        import cppjit

        cppjit.add_include_path(str(currpath.join("cpp", "MemoryOwnership")))
        cppjit.include("../memory_analysis.h")
        cppjit.include("memory_analysis_redecl.h")
        cls.memory_analysis = cppjit.load_library(cls.test_dct + ".so")

    def test01_malloc_attr(self):
        import cppjit

        obj = cppjit.gbl.memory.mallocAttr()
        assert type(obj) == cppjit.gbl.memory.memAnalysisKlass
        assert obj.__python_owns__
        assert obj.__is_malloc__

    def test02_ownership_returns_attr(self):
        import cppjit

        obj = cppjit.gbl.memory.ownershipReturnsAttr()
        assert type(obj) == cppjit.gbl.memory.memAnalysisKlass
        assert obj.__python_owns__
        assert obj.__is_malloc__

    def test03_no_attr(self):
        import cppjit

        obj = cppjit.gbl.memory.noAttr()
        assert type(obj) == cppjit.gbl.memory.memAnalysisKlass
        assert not obj.__python_owns__
        obj.__python_owns__ = True

    def test04_redecl_attr(self):
        import cppjit

        cppjit.gbl.memory.memOwn.dtorCount = 0

        obj = cppjit.gbl.memory.allocDefaultMemOwn()
        assert type(obj) == cppjit.gbl.memory.memOwn
        assert obj.__python_owns__
        assert not obj.__is_malloc__
        assert not obj.__is_no_construct__
        assert not obj.__is_array_alloc__

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 1

    def test05_redecl_no_attr(self):
        import cppjit

        obj = cppjit.gbl.memory.noAttrAlloc()
        assert type(obj) == cppjit.gbl.memory.memOwn
        assert not obj.__python_owns__
        obj.__python_owns__ = True

        # Setting only python_owns, intends object is allocated with new
        assert not obj.__is_malloc__
        assert not obj.__is_no_construct__
        assert not obj.__is_array_alloc__

    def test08_allocwith_operator_newarr_attr(self):
        import cppjit

        cppjit.gbl.memory.memOwn.dtorCount = 0

        obj = cppjit.gbl.memory.allocOperatorNewArrAttr(5)
        assert obj.__python_owns__
        assert obj.__is_no_construct__
        assert obj.__is_array_alloc__

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    def test09_allocwith_newarr_attr(self):
        import cppjit

        cppjit.gbl.memory.memOwn.dtorCount = 0

        obj = cppjit.gbl.memory.allocNewArrAttr(5)
        assert obj.__python_owns__
        assert not obj.__is_no_construct__
        assert obj.__is_array_alloc__

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 5

    def test10_allocwith_malloc_attr(self):
        import cppjit

        cppjit.gbl.memory.memOwn.dtorCount = 0

        obj = cppjit.gbl.memory.allocMallocAttr(5)
        assert obj.__python_owns__
        assert not obj.__is_no_construct__
        assert not obj.__is_array_alloc__
        assert obj.__is_malloc__

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    def test11_allocwith_operator_new_attr(self):
        import cppjit

        cppjit.gbl.memory.memOwn.dtorCount = 0

        obj = cppjit.gbl.memory.allocOperatorNewAttr()
        assert obj.__python_owns__
        assert obj.__is_no_construct__
        assert not obj.__is_array_alloc__
        assert not obj.__is_malloc__

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    def test12_double_free_with_gblfree(self):
        import cppjit

        obj = cppjit.gbl.memory.mallocAttr()
        assert obj.__python_owns__
        assert obj.__is_malloc__
        cppjit.gbl.free(obj)
        assert not obj.__python_owns__

    def test13_double_free_with_ownership_takes(self):
        import cppjit

        obj = cppjit.gbl.memory.mallocAttr()
        assert obj.__python_owns__
        assert obj.__is_malloc__
        cppjit.gbl.memory.ownershipTakesAttr(obj)
        assert not obj.__python_owns__

    def test14_double_free_with_not_ownership_taken(self):
        import cppjit

        obj = cppjit.gbl.memory.mallocAttr()
        assert obj.__python_owns__
        assert obj.__is_malloc__
        cppjit.gbl.memory.takesPtrButNotOwnership(obj)
        assert obj.__python_owns__


@mark.skipif(not IN_CHILD, reason="needs " + FLAGS)
class TestMEMORYANALYSIS_APINOTES:
    def setup_class(cls):
        cls.test_dct = test_dct
        import cppjit

        cppjit.add_include_path(str(currpath.join("cpp", "MemoryOwnership")))
        cppjit.include("../memory_analysis.h")
        cls.memory_analysis = cppjit.load_library(cls.test_dct + ".so")

    def test01_apinotes_attr_method(self):
        import cppjit

        obj = cppjit.gbl.memory.memOwn.memOwnAllocator(5)
        assert type(obj) == cppjit.gbl.memory.memOwn
        assert obj.__python_owns__

    def test02_apinotes_attr_func(self):
        import cppjit

        obj = cppjit.gbl.memory.memOwnOperatorNew()
        assert type(obj) == cppjit.gbl.memory.memOwn
        assert obj.__python_owns__
        assert obj.__is_no_construct__
