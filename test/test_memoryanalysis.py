import os
import subprocess
import sys

import py
from pytest import mark
from support import IS_CLING, setup_make

currpath = py.path.local(__file__).dirpath()
test_dct = str(currpath.join("cpp/memory_analysisDict"))

FLAGS = "-fmodules -fimplicit-module-maps -fapinotes-modules"
IN_CHILD = "-fapinotes-modules" in os.getenv("CPPINTEROP_EXTRA_INTERPRETER_ARGS", "")


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

    def test02_ownership_returns_attr(self):
        import cppjit

        obj = cppjit.gbl.memory.ownershipReturnsAttr()
        assert type(obj) == cppjit.gbl.memory.memAnalysisKlass
        assert obj.__python_owns__

    def test03_no_attr(self):
        import cppjit

        obj = cppjit.gbl.memory.noAttr()
        assert type(obj) == cppjit.gbl.memory.memAnalysisKlass
        assert not obj.__python_owns__
        obj.__python_owns__ = True

    def test04_redecl_attr(self):
        import cppjit

        obj = cppjit.gbl.memory.allocDefaultMemOwn()
        assert type(obj) == cppjit.gbl.memory.memOwn
        assert obj.__python_owns__

    def test05_redecl_no_attr(self):
        import cppjit

        obj = cppjit.gbl.memory.noAttrAlloc()
        assert type(obj) == cppjit.gbl.memory.memOwn
        assert not obj.__python_owns__
        obj.__python_owns__ = True


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

        obj = cppjit.gbl.memory.memOwnAllocGlobal()
        assert type(obj) == cppjit.gbl.memory.memOwn
        assert obj.__python_owns__
