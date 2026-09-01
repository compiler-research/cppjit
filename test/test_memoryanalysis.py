import os
import subprocess
import sys

import py
from pytest import mark
from support import IS_CLANG_LT_22, IS_CLING, setup_make

currpath = py.path.local(__file__).dirpath()
test_dct = str(currpath.join("cpp/memory_analysisDict"))

FLAGS = "-fmodules -fimplicit-module-maps -fapinotes-modules"
IN_CHILD = "-fapinotes-modules" in os.getenv("CPPINTEROP_EXTRA_INTERPRETER_ARGS", "")

skip_if_inline_from_module = mark.skipif(
    IN_CHILD and IS_CLANG_LT_22,
    reason="LLVM < 22 does not emit inline definitions that come from a module",
)


def setup_module(mod):
    setup_make("memory_analysis")


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

        def alloc():
            obj = cppjit.gbl.memory.allocDefaultMemOwn()
            assert type(obj) == cppjit.gbl.memory.memOwn
            assert obj.__python_owns__
            assert not obj.__is_malloc__
            assert not obj.__is_no_construct__
            assert not obj.__is_array_alloc__

        alloc()
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

    @skip_if_inline_from_module
    def test06_analyzer_on(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        obj = cppjit.gbl.memory.allocAnalyzerOn()
        assert obj.__python_owns__

    @skip_if_inline_from_module
    def test07_analyzer_off(self):
        import cppjit

        cppjit.use_alloc_analyzer(False)
        obj = cppjit.gbl.memory.allocAnalyzerOff()
        assert not (obj.__python_owns__)
        obj.__python_owns__ = True

    @skip_if_inline_from_module
    def test08_analyzer_off_but_cache(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        obj = cppjit.gbl.memory.allocAnalyzerOn()
        assert obj.__python_owns__

        cppjit.use_alloc_analyzer(False)
        obj2 = cppjit.gbl.memory.allocAnalyzerOn()
        assert obj2.__python_owns__

    @skip_if_inline_from_module
    def test09_allocwith_operator_newarr(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        def alloc():
            obj = cppjit.gbl.memory.allocOperatorNewArr(5)
            assert obj.__python_owns__
            assert obj.__is_no_construct__
            assert obj.__is_array_alloc__

        alloc()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    @skip_if_inline_from_module
    def test10_allocwith_newarr(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        def alloc():
            obj = cppjit.gbl.memory.allocNewArr(5)
            assert obj.__python_owns__
            assert not obj.__is_no_construct__
            assert obj.__is_array_alloc__

        alloc()
        assert cppjit.gbl.memory.memOwn.dtorCount == 5

    @skip_if_inline_from_module
    def test11_allocwith_malloc(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        def alloc():
            obj = cppjit.gbl.memory.allocMalloc(5)
            assert obj.__python_owns__
            assert not obj.__is_no_construct__
            assert not obj.__is_array_alloc__
            assert obj.__is_malloc__

        alloc()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    @skip_if_inline_from_module
    def test12_allocwith_operator_new(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        def alloc():
            obj = cppjit.gbl.memory.allocOperatorNew()
            assert obj.__python_owns__
            assert obj.__is_no_construct__
            assert not obj.__is_array_alloc__
            assert not obj.__is_malloc__

        alloc()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    def test13_allocwith_operator_newarr_attr(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        def alloc():
            obj = cppjit.gbl.memory.allocOperatorNewArrAttr(5)
            assert obj.__python_owns__
            assert obj.__is_no_construct__
            assert obj.__is_array_alloc__

        alloc()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    def test14_allocwith_newarr_attr(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        def alloc():
            obj = cppjit.gbl.memory.allocNewArrAttr(5)
            assert obj.__python_owns__
            assert not obj.__is_no_construct__
            assert obj.__is_array_alloc__

        alloc()
        assert cppjit.gbl.memory.memOwn.dtorCount == 5

    def test15_allocwith_malloc_attr(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        def alloc():
            obj = cppjit.gbl.memory.allocMallocAttr(5)
            assert obj.__python_owns__
            assert not obj.__is_no_construct__
            assert not obj.__is_array_alloc__
            assert obj.__is_malloc__

        alloc()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    def test16_allocwith_operator_new_attr(self):
        import cppjit

        cppjit.use_alloc_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        def alloc():
            obj = cppjit.gbl.memory.allocOperatorNewAttr()
            assert obj.__python_owns__
            assert obj.__is_no_construct__
            assert not obj.__is_array_alloc__
            assert not obj.__is_malloc__

        alloc()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0


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
