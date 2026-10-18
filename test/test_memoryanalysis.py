import gc
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

    # The tests below check the mapping from a call argument to the parameter
    # that the deallocation attribute labels. Every call releases the object
    # in C++, so Python has to give up the ownership of it.

    def owned_memown(self):
        import cppjit

        obj = cppjit.gbl.memory.allocDefaultMemOwn()
        assert obj.__python_owns__
        return obj

    def test15_release_bound_positional(self):
        import cppjit

        cppjit.gbl.memory.memOwn.dtorCount = 0
        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        owner.release(obj)
        assert not obj.__python_owns__
        assert cppjit.gbl.memory.memOwn.dtorCount == 1

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 1

    def test16_release_bound_keyword(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        owner.release(obj=obj)
        assert not obj.__python_owns__

    def test17_release_unbound_positional(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        cppjit.gbl.memory.memOwner.release(owner, obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test18_release_unbound_keyword(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        cppjit.gbl.memory.memOwner.release(owner, obj=obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test19_release_second_positional(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        keep = self.owned_memown()
        obj = self.owned_memown()

        owner.releaseSecond(keep, obj)
        assert not obj.__python_owns__
        assert keep.__python_owns__

    def test20_release_second_keyword_reversed(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        keep = self.owned_memown()
        obj = self.owned_memown()

        # the values arrive in call order, so only the names say which
        # parameter each one belongs to
        owner.releaseSecond(obj=obj, keep=keep)
        assert not obj.__python_owns__
        assert keep.__python_owns__

    def test21_release_after_count(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        owner.releaseAfterCount(3, obj)
        assert not obj.__python_owns__

    def test22_release_after_count_keyword(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        owner.releaseAfterCount(count=3, obj=obj)
        assert not obj.__python_owns__

    def test23_keep_ownership(self):
        import cppjit

        cppjit.gbl.memory.memOwn.dtorCount = 0
        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        owner.keepOwnership(obj)
        assert obj.__python_owns__
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

        owner.keepOwnership(obj=obj)
        assert obj.__python_owns__

    def test24_release_static_through_instance(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        # a static method has no implicit this slot, although the lookup on an
        # instance binds self
        owner.releaseStatic(obj)
        assert not obj.__python_owns__

    def test25_release_static_through_class(self):
        import cppjit

        obj = self.owned_memown()

        cppjit.gbl.memory.memOwner.releaseStatic(obj)
        assert not obj.__python_owns__

    def test26_release_static_with_leading_instance(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        # cppjit drops the leading instance of such a call, so the first
        # parameter is the second argument
        cppjit.gbl.memory.memOwner.releaseStatic(owner, obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test27_release_free_function(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        cppjit.gbl.memory.releaseFree(owner, obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test28_release_free_function_keyword(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        cppjit.gbl.memory.releaseFree(owner, obj=obj)
        assert not obj.__python_owns__

    def test29_release_free_function_attached(self):
        import cppjit

        # a free function whose first parameter is the object works as a
        # method, and then cppjit passes self as that parameter
        cppjit.gbl.memory.memOwner.releaseAttached = cppjit.gbl.memory.releaseFree
        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        owner.releaseAttached(obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test30_release_free_function_attached_keyword(self):
        import cppjit

        cppjit.gbl.memory.memOwner.releaseAttached = cppjit.gbl.memory.releaseFree
        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        owner.releaseAttached(obj=obj)
        assert not obj.__python_owns__

    # A direct call keeps self inside the argument array, as the vector call
    # skips the descriptor. Storing the method first runs the descriptor, and
    # then self arrives on its own.

    def test31_release_stored_bound_positional(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        release = owner.release
        release(obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test32_release_stored_bound_keyword(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        release = owner.release
        release(obj=obj)
        assert not obj.__python_owns__

    def test33_release_second_stored_bound(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        keep = self.owned_memown()
        obj = self.owned_memown()

        release_second = owner.releaseSecond
        release_second(keep, obj)
        assert not obj.__python_owns__
        assert keep.__python_owns__

    def test34_release_static_stored_bound(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        release_static = owner.releaseStatic
        release_static(obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test35_release_free_function_attached_stored_bound(self):
        import cppjit

        cppjit.gbl.memory.memOwner.releaseAttached = cppjit.gbl.memory.releaseFree
        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        release_attached = owner.releaseAttached
        release_attached(obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test36_keep_ownership_stored_bound(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        obj = self.owned_memown()

        keep_ownership = owner.keepOwnership
        keep_ownership(obj)
        assert obj.__python_owns__

    def test37_python_overload(self):
        import cppjit

        owner = cppjit.gbl.memory.memOwner()
        keep = self.owned_memown()
        obj = self.owned_memown()

        def extra(self, obj):
            return 0

        cppjit.gbl.memory.memOwner.releaseOverloaded.__add_overload__(extra)

        # a Python overload carries no ownership information, so the arguments
        # of such a call keep their ownership
        owner.releaseOverloaded(obj)
        assert obj.__python_owns__
        assert owner.__python_owns__

        # the name of a Python argument is no C++ parameter name either
        owner.releaseOverloaded(obj=obj)
        assert obj.__python_owns__

        # the C++ overload needs two arguments, and it does take the ownership
        owner.releaseOverloaded(keep, obj)
        assert not obj.__python_owns__
        assert keep.__python_owns__

    def test38_bind_object_keeps_the_allocation_kind(self):
        import cppjit

        obj = cppjit.gbl.memory.allocMallocDerived()
        assert obj.__python_owns__
        assert obj.__is_malloc__

        # a cast moves the ownership to the new proxy, so the deallocator of
        # the memory has to move with it
        cast = cppjit.bind_object(obj, cppjit.gbl.memory.memCastBase)
        assert not obj.__python_owns__
        assert cast.__python_owns__
        assert cast.__is_malloc__

        del cast
        gc.collect()


class TestLOWLEVELVIEWMEMORY:
    def setup_class(cls):
        cls.test_dct = test_dct
        import cppjit

        cppjit.add_include_path(str(currpath.join("cpp", "MemoryOwnership")))
        cppjit.include("../memory_analysis.h")
        cls.memory_analysis = cppjit.load_library(cls.test_dct + ".so")

    def test01_newarr_attr(self):
        import cppjit
        import cppjit.types

        view = cppjit.gbl.memory.allocIntNewArr(4)
        assert type(view) == cppjit.types.LowLevelView
        assert view.__python_owns__
        assert view.__cpp_array__
        assert not view.__is_new__

        # the view frees the buffer with ::operator delete[]
        del view
        gc.collect()

    def test02_operator_newarr_attr(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntOperatorNewArr(4)
        assert view.__python_owns__
        assert view.__cpp_array__
        assert not view.__is_new__

        del view
        gc.collect()

    def test03_new_attr(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntNew()
        assert view.__python_owns__
        assert view.__is_new__
        assert not view.__cpp_array__

        # the view frees the buffer with ::operator delete
        del view
        gc.collect()

    def test04_operator_new_attr(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntOperatorNew()
        assert view.__python_owns__
        assert view.__is_new__
        assert not view.__cpp_array__

        del view
        gc.collect()

    def test05_malloc_attr(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntMalloc(4)
        assert view.__python_owns__
        # malloc has no flag of its own: no allocation flag means free()
        assert not view.__cpp_array__
        assert not view.__is_new__

        del view
        gc.collect()

    def test06_no_attr(self):
        import cppjit

        view = cppjit.gbl.memory.intNoAttrAlloc()
        assert not view.__python_owns__

        # function has no attribute, so the flags stay as ll_new wrote them:
        # the user takes ownership, therefore the default delete[] is called
        view.__python_owns__ = True
        assert view.__cpp_array__
        assert not view.__is_new__

        del view
        gc.collect()

    def test07_release_newarr_buffer(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntNewArr(4)
        assert view.__python_owns__

        cppjit.gbl.memory.releaseBufferArr(view)
        assert not view.__python_owns__

        del view
        gc.collect()

    def test08_release_newarr_buffer_keyword(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntNewArr(4)

        cppjit.gbl.memory.releaseBufferArr(buf=view)
        assert not view.__python_owns__

    def test09_release_new_buffer(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntNew()

        cppjit.gbl.memory.releaseBuffer(view)
        assert not view.__python_owns__

        del view
        gc.collect()

    def test10_release_malloc_buffer(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntMalloc(4)

        cppjit.gbl.memory.releaseBufferMalloc(view)
        assert not view.__python_owns__

        del view
        gc.collect()

    def test11_keep_buffer(self):
        import cppjit

        view = cppjit.gbl.memory.allocIntNewArr(4)

        # a cppDeallocNone parameter leaves the ownership where it was
        cppjit.gbl.memory.keepBuffer(view)
        assert view.__python_owns__

        del view
        gc.collect()

    def test12_release_with_free(self):
        import cppjit

        view = cppjit.gbl.malloc(16)

        cppjit.gbl.free(view)
        assert not view.__python_owns__

        del view
        gc.collect()


class TestMEMORYANALYZER:
    def setup_class(cls):
        cls.test_dct = test_dct
        import cppjit

        cppjit.add_include_path(str(currpath.join("cpp", "MemoryOwnership")))
        cppjit.include("../memory_analysis.h")
        cls.memory_analysis = cppjit.load_library(cls.test_dct + ".so")

    def teardown_class(cls):
        import cppjit

        # the flag is global, so the tests that follow must not inherit it
        cppjit.use_memory_analyzer(False)

    def test01_alloc_with_analyzer_off(self):
        import cppjit

        cppjit.use_memory_analyzer(False)

        obj = cppjit.gbl.memory.analyzerOffAllocNew()
        assert not obj.__python_owns__

        obj.__python_owns__ = True

    def test02_alloc_with_new(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        obj = cppjit.gbl.memory.analyzerAllocNew()
        assert obj.__python_owns__
        assert not obj.__is_array_alloc__
        assert not obj.__is_malloc__

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 1

    def test03_alloc_with_newarr(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        obj = cppjit.gbl.memory.analyzerAllocNewArr()
        assert obj.__python_owns__
        assert obj.__is_array_alloc__

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 5

    def test04_alloc_with_malloc(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0

        obj = cppjit.gbl.memory.analyzerAllocMalloc()
        assert obj.__python_owns__
        assert obj.__is_malloc__

        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

    def test05_cached_answer_(self):
        import cppjit

        cppjit.use_memory_analyzer(True)

        first = cppjit.gbl.memory.analyzerCachedAllocNew()
        assert first.__python_owns__

        cppjit.use_memory_analyzer(False)
        second = cppjit.gbl.memory.analyzerCachedAllocNew()
        assert second.__python_owns__

    def test06_release_bound_positional(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        owner = cppjit.gbl.memory.analyzerOwner()
        obj = cppjit.gbl.memory.memOwn(5)
        assert obj.__python_owns__

        owner.analyzerRelease(obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test07_release_bound_keyword(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        owner = cppjit.gbl.memory.analyzerOwner()
        obj = cppjit.gbl.memory.memOwn(5)

        owner.analyzerRelease(obj=obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test08_release_unbound_positional(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        owner = cppjit.gbl.memory.analyzerOwner()
        obj = cppjit.gbl.memory.memOwn(5)

        cppjit.gbl.memory.analyzerOwner.analyzerRelease(owner, obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test09_release_second_parameter(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        owner = cppjit.gbl.memory.analyzerOwner()
        keep = cppjit.gbl.memory.memOwn(5)
        obj = cppjit.gbl.memory.memOwn(5)

        owner.analyzerReleaseSecond(keep, obj)
        assert not obj.__python_owns__
        assert keep.__python_owns__
        assert owner.__python_owns__

    def test10_release_second_parameter_keyword_reversed(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        owner = cppjit.gbl.memory.analyzerOwner()
        keep = cppjit.gbl.memory.memOwn(5)
        obj = cppjit.gbl.memory.memOwn(5)

        owner.analyzerReleaseSecond(obj=obj, keep=keep)
        assert not obj.__python_owns__
        assert keep.__python_owns__

    def test11_release_static_from_class(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        obj = cppjit.gbl.memory.memOwn(5)

        cppjit.gbl.memory.analyzerOwner.analyzerReleaseStatic(obj)
        assert not obj.__python_owns__

    def test12_release_static_from_instance(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        owner = cppjit.gbl.memory.analyzerOwner()
        obj = cppjit.gbl.memory.memOwn(5)

        owner.analyzerReleaseStatic(obj)
        assert not obj.__python_owns__
        assert owner.__python_owns__

    def test13_release_free_function(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        obj = cppjit.gbl.memory.memOwn(5)

        cppjit.gbl.memory.analyzerReleaseFree(obj)
        assert not obj.__python_owns__

    def test14_attribute_wins(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        cppjit.gbl.memory.memOwn.dtorCount = 0
        owner = cppjit.gbl.memory.analyzerOwner()
        obj = cppjit.gbl.memory.memOwn(5)

        owner.analyzerAttrWins(obj)
        # the attribute says delete although the body frees nothing, and the
        # attribute wins
        assert not obj.__python_owns__
        assert cppjit.gbl.memory.memOwn.dtorCount == 0

        obj.__python_owns__ = True
        del obj
        gc.collect()
        assert cppjit.gbl.memory.memOwn.dtorCount == 1

    def test15_attribute_and_body_on_different_arg(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        owner = cppjit.gbl.memory.analyzerOwner()
        keep = cppjit.gbl.memory.memOwn(5)
        obj = cppjit.gbl.memory.memOwn(5)

        owner.analyzerMixedSlots(keep, obj)
        assert keep.__python_owns__
        assert not obj.__python_owns__

    def test16_release_with_analyzer_off(self):
        import cppjit

        cppjit.use_memory_analyzer(False)
        owner = cppjit.gbl.memory.analyzerOwner()
        obj = cppjit.gbl.memory.memOwn(5)

        owner.analyzerOffRelease(obj)
        assert obj.__python_owns__

        obj.__python_owns__ = False

    def test17_release_without_a_body(self):
        import cppjit

        cppjit.use_memory_analyzer(True)
        obj = cppjit.gbl.memory.memOwn(5)

        cppjit.gbl.memory.analyzerNoBodyRelease(obj)
        assert obj.__python_owns__

        obj.__python_owns__ = False


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
