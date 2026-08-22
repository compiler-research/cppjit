import py
from support import setup_make

currpath = py.path.local(__file__).dirpath()
test_dct = str(currpath.join("cpp/memory_analysisDict"))


def setup_module(mod):
    setup_make("memory_analysis")


class TestMEMORYANALYSIS:
    def setup_class(cls):
        cls.test_dct = test_dct
        import cppjit

        cls.memory_analysis = cppjit.load_reflection_info(cls.test_dct)

    def test01_malloc_attr(self):
        import cppjit

        obj = cppjit.gbl.allocTest()
        assert type(obj) == cppjit.gbl.memAnalysisKlass
        assert obj.__python_owns__

    def test02_ownership_returns_attr(self):
        import cppjit

        obj = cppjit.gbl.allocTestReturns()
        assert type(obj) == cppjit.gbl.memAnalysisKlass
        assert obj.__python_owns__

    def test03_analyzer_new(self):
        import cppjit

        cppjit._backend.SetUseAllocAnalyzer(True)
        obj = cppjit.gbl.allocNew()
        assert type(obj) == cppjit.gbl.memAnalysisKlass
        assert obj.__python_owns__

    def test04_analyzer_new_default(self):
        import cppjit

        cppjit._backend.SetUseAllocAnalyzer(False)
        obj = cppjit.gbl.allocNew2()
        assert type(obj) == cppjit.gbl.memAnalysisKlass
        assert not (obj.__python_owns__)
        obj.__python_owns__ = True
