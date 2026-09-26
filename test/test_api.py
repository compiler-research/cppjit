import subprocess
import sys

from pytest import mark, raises, skip
from support import CAN_JIT_STD_FILESYSTEM, IS_LINUX_ARM, IS_MAC, ispypy


class TestAPI:
    def setup_class(cls):
        if ispypy:
            skip("C++ API only available on CPython")

        import cppjit

        cppjit.include("cpyrt/API.h")

    def test01_type_checking(self):
        """Python class type checks"""

        import cppjit

        cpp = cppjit.gbl
        API = cpp.cppjit.cpyrt

        cppjit.cppdef("""
        class APICheck {
        public:
          void some_method() {}
        };""")

        assert API.Scope_Check(cpp.APICheck)
        assert not API.Scope_CheckExact(cpp.APICheck)

        a = cpp.APICheck()
        assert API.Instance_Check(a)
        assert not API.Instance_CheckExact(a)

        m = a.some_method
        assert API.Overload_Check(m)
        assert API.Overload_CheckExact(m)

    @mark.xfail(condition=IS_MAC, reason="Fails on OS X")
    def test02_interpreter_access(self):
        """Access to the python interpreter"""

        import cppjit

        API = cppjit.gbl.cppjit.cpyrt

        assert API.Exec("import sys")

    @mark.xfail(condition=IS_MAC, reason="Fails on OS X")
    def test03_instance_conversion(self):
        """Proxy object conversions"""

        import cppjit

        cpp = cppjit.gbl
        API = cpp.cppjit.cpyrt

        cppjit.cppdef("""
        class APICheck2 {
        public:
          virtual ~APICheck2() {}
        };""")

        m = cpp.APICheck2()

        voidp = API.Instance_AsVoidPtr(m)
        m2 = API.Instance_FromVoidPtr(voidp, "APICheck2")
        assert m is m2

    @mark.xfail(condition=IS_LINUX_ARM, run=False, reason="Crashes pytest on Linux ARM")
    def test04_custom_converter(self):
        """Custom type converter"""

        import cppjit

        cppjit.cppdef("""
        #include "cpyrt/API.h"

        class APICheck3 {
            int fFlags;
        public:
            APICheck3() : fFlags(0) {}
            virtual ~APICheck3() {}

            void setSetArgCalled()     { fFlags |= 0x01; }
            bool wasSetArgCalled()     { return fFlags & 0x01; }
            void setFromMemoryCalled() { fFlags |= 0x02; }
            bool wasFromMemoryCalled() { return fFlags & 0x02; }
            void setToMemoryCalled()   { fFlags |= 0x04; }
            bool wasToMemoryCalled()   { return fFlags & 0x04; }
        };

        class APICheck3Converter : public cppjit::cpyrt::Converter {
        public:
            virtual bool SetArg(PyObject* pyobject, cppjit::cpyrt::Parameter& para, cppjit::cpyrt::CallContext* = nullptr) {
                APICheck3* a3 = (APICheck3*)cppjit::cpyrt::Instance_AsVoidPtr(pyobject);
                a3->setSetArgCalled();
                para.fValue.fVoidp = a3;
                para.fTypeCode = 'V';
                return true;
            }

            virtual PyObject* FromMemory(void* address) {
                APICheck3* a3 = (APICheck3*)address;
                a3->setFromMemoryCalled();
                return cppjit::cpyrt::Instance_FromVoidPtr(a3, "APICheck3");
            }

            virtual bool ToMemory(PyObject* value, void* address) {
                APICheck3* a3 = (APICheck3*)address;
                a3->setToMemoryCalled();
                *a3 = *(APICheck3*)cppjit::cpyrt::Instance_AsVoidPtr(value);
                return true;
            }
        };

        typedef cppjit::cpyrt::ConverterFactory_t cf_t;
        void register_a3() {
            cppjit::cpyrt::RegisterConverter("APICheck3",  (cf_t)+[](cppjit::cpyrt::cdims_t) { static APICheck3Converter c{}; return &c; });
            cppjit::cpyrt::RegisterConverter("APICheck3&", (cf_t)+[](cppjit::cpyrt::cdims_t) { static APICheck3Converter c{}; return &c; });
        }
        void unregister_a3() {
            cppjit::cpyrt::UnregisterConverter("APICheck3");
            cppjit::cpyrt::UnregisterConverter("APICheck3&");
        }

        APICheck3 gA3a, gA3b;
        void CallWithAPICheck3(APICheck3&) {}
        """)

        cppjit.gbl.register_a3()

        gA3a = cppjit.gbl.gA3a
        assert gA3a
        assert type(gA3a) == cppjit.gbl.APICheck3
        assert gA3a.wasFromMemoryCalled()

        assert not gA3a.wasSetArgCalled()
        cppjit.gbl.CallWithAPICheck3(gA3a)
        assert gA3a.wasSetArgCalled()

        cppjit.gbl.unregister_a3()

        gA3b = cppjit.gbl.gA3b
        assert gA3b
        assert type(gA3b) == cppjit.gbl.APICheck3
        assert not gA3b.wasFromMemoryCalled()

    @mark.xfail(condition=IS_LINUX_ARM, run=False, reason="Crashes pytest on Linux ARM")
    def test05_custom_executor(self):
        """Custom type executor"""

        import cppjit

        cppjit.cppdef("""
        #include "cpyrt/API.h"

        class APICheck4 {
            int fFlags;
        public:
            APICheck4() : fFlags(0) {}
            virtual ~APICheck4() {}

            void setExecutorCalled() { fFlags |= 0x01; }
            bool wasExecutorCalled() { return fFlags & 0x01; }
        };

        class APICheck4Executor : public cppjit::cpyrt::Executor {
        public:
             virtual PyObject* Execute(cppjit::interop::TCppMethod_t meth, cppjit::interop::TCppObject_t obj, cppjit::cpyrt::CallContext* ctxt) {
                 APICheck4* a4 = (APICheck4*)cppjit::cpyrt::CallVoidP(meth, obj, ctxt);
                 a4->setExecutorCalled();
                 return cppjit::cpyrt::Instance_FromVoidPtr(a4, "APICheck4", true);
             }
        };

        typedef cppjit::cpyrt::ExecutorFactory_t ef_t;
        void register_a4() {
            cppjit::cpyrt::RegisterExecutor("APICheck4*", (ef_t)+[](cppjit::cpyrt::cdims_t) { static APICheck4Executor c{}; return &c; });
        }
        void unregister_a4() {
            cppjit::cpyrt::UnregisterExecutor("APICheck4*");
        }

        APICheck4* CreateAPICheck4() { return new APICheck4{}; }
        APICheck4* CreateAPICheck4b() { return new APICheck4{}; }
        """)

        cppjit.gbl.register_a4()

        a4 = cppjit.gbl.CreateAPICheck4()
        assert a4
        assert type(a4) == cppjit.gbl.APICheck4
        assert a4.wasExecutorCalled()
        del a4

        cppjit.gbl.unregister_a4()

        a4 = cppjit.gbl.CreateAPICheck4b()
        assert a4
        assert type(a4) == cppjit.gbl.APICheck4
        assert not a4.wasExecutorCalled()

    def test06_custom_executor(self):
        """Custom type executor"""

        import cppjit

        cppjit.cppdef("""
        #include "cpyrt/API.h"

        namespace ArrayLike {
        class MyClass{};
        MyClass* my = nullptr;
        MyClass  myA[5];

        class MyArray {
        public:
            int operator[](int) { return 42; }
        }; }""")

        ns = cppjit.gbl.ArrayLike
        Sequence_Check = cppjit.gbl.cppjit.cpyrt.Sequence_Check

        assert not Sequence_Check(ns.my)
        assert Sequence_Check(ns.myA)
        assert not Sequence_Check(ns.MyClass())
        assert Sequence_Check(ns.MyArray())
        assert Sequence_Check(tuple())
        assert Sequence_Check(cppjit.gbl.std.vector[ns.MyClass]())
        assert not Sequence_Check(cppjit.gbl.std.list[ns.MyClass]())


class TestJITERRORS:
    def test01_diagnostics_stay_out_of_stderr(self, capfd):
        """A compile error's text lands in the exception, not on fd 2"""

        import cppjit

        with raises(SyntaxError) as e:
            cppjit.cppdef("1aap = 42;")
        assert "invalid digit" in str(e.value)

        out, err = capfd.readouterr()
        assert "invalid digit" not in err

    @staticmethod
    def _run_child(code):
        # A failed materialization poisons the JIT session (see test04), so
        # every call that is meant to fail runs in a process of its own.
        return subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

    def test02_missing_runtime_symbol_raises(self):
        """A stdlib feature the runtime lacks raises at the call, the process lives"""

        # std::filesystem parses against any C++17 headers, yet its symbols
        # live in the loaded libstdc++.so and a GCC 8 runtime has none. The
        # child must reach EXIT_OK either way.
        child = (
            "import cppjit\n"
            "try:\n"
            '    cppjit.cppdef("""#include <filesystem>\n'
            "    int fs_probe() {\n"
            '        std::filesystem::path p{"/tmp/a/b.txt"};\n'
            "        return (int)p.filename().string().size();\n"
            '    }""")\n'
            "    print('DECLARED')\n"
            "    print('PROBE', cppjit.gbl.fs_probe())\n"
            "except BaseException as e:\n"
            "    print('CAUGHT %s: %s' % (type(e).__name__, e))\n"
            "cppjit.cppdef('int after_probe() { return 7; }')\n"
            "print('AFTER_PROBE', cppjit.gbl.after_probe())\n"
            "print('EXIT_OK')\n"
        )
        proc = self._run_child(child)

        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert "EXIT_OK" in proc.stdout
        assert "AFTER_PROBE 7" in proc.stdout
        assert "CppInterOp CRASH DETECTED" not in proc.stderr
        # the declaration goes through everywhere
        assert "DECLARED" in proc.stdout, (proc.stdout, proc.stderr)

        if CAN_JIT_STD_FILESYSTEM:
            assert "PROBE 5" in proc.stdout, (proc.stdout, proc.stderr)
        else:
            # the first call raises, and names the missing symbol
            assert "CAUGHT" in proc.stdout, (proc.stdout, proc.stderr)
            assert proc.stdout.index("DECLARED") < proc.stdout.index("CAUGHT")
            assert "filesystem" in proc.stdout + proc.stderr, (
                proc.stdout,
                proc.stderr,
            )

    def test03_failed_wrapper_raises_for_every_return_type(self):
        """A call wrapper the JIT cannot compile raises whatever the return type"""

        # undefined_fn_x is declared but never defined, so the first call to
        # each function fails to materialize. One cppdef per function keeps
        # each in a module of its own, so every failure names the root cause
        # instead of the module a previous failure took down. Opaque is never
        # completed, so make_opaque's return buffer has no size and no
        # wrapper is compiled.
        child = (
            "import cppjit\n"
            "cppjit.cppdef('extern int undefined_fn_x();')\n"
            "cppjit.cppdef('int f_i() { return undefined_fn_x(); }')\n"
            "cppjit.cppdef('void f_v() { undefined_fn_x(); }')\n"
            "cppjit.cppdef('std::string f_s() { undefined_fn_x(); return \"\"; }')\n"
            "cppjit.cppdef('struct Opaque; Opaque make_opaque();')\n"
            "for name in ('f_i', 'f_v', 'f_s', 'make_opaque'):\n"
            "    try:\n"
            "        print('RETURNED', name, repr(getattr(cppjit.gbl, name)()))\n"
            "    except BaseException as e:\n"
            "        print('RAISED', name, type(e).__name__,"
            " str(e).replace('\\n', ' | '))\n"
            "print('EXIT_OK')\n"
        )
        proc = self._run_child(child)

        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert "EXIT_OK" in proc.stdout
        assert "RETURNED" not in proc.stdout, proc.stdout
        lines = proc.stdout.splitlines()

        for name in ("f_i", "f_v", "f_s"):
            raised = [l for l in lines if l.startswith("RAISED %s " % name)]
            assert raised, (name, proc.stdout, proc.stderr)
            assert "RuntimeError" in raised[0], raised[0]
            assert "failed to JIT-compile the call wrapper" in raised[0]
            assert "undefined_fn_x" in raised[0], raised[0]

        # the unsizable return keeps its own diagnosis
        raised = [l for l in lines if l.startswith("RAISED make_opaque ")]
        assert raised, (proc.stdout, proc.stderr)
        assert "ValueError" in raised[0], raised[0]
        assert "the size of its return type is unknown" in raised[0], raised[0]

    @mark.xfail(
        strict=True,
        reason="ORC marks a failed module's linkonce_odr first-definitions "
        "failed and later weak definitions do not replace them. Root fix "
        "pending.",
    )
    def test04_failed_materialization_keeps_later_std_code_working(self):
        """Unrelated std::string code still JIT-compiles after a failed call"""

        # first_s is the session's first std::string user, so its module also
        # carries the first definitions of the std::string members it uses
        child = (
            "import cppjit\n"
            "cppjit.cppdef('extern int undefined_fn_p();"
            ' std::string first_s() { undefined_fn_p(); return ""; }\')\n'
            "try:\n"
            "    cppjit.gbl.first_s()\n"
            "except BaseException:\n"
            "    pass\n"
            "cppjit.cppdef('std::string second_s() { return \"ok\"; }')\n"
            "if str(cppjit.gbl.second_s()) == 'ok':\n"
            "    print('SECOND_OK')\n"
        )
        proc = self._run_child(child)

        assert "SECOND_OK" in proc.stdout, (proc.stdout, proc.stderr)

    def test05_failed_wrapper_inside_a_pythonization_raises(self):
        """A pythonized method whose C++ call cannot be JIT-compiled raises"""

        # The constructor's wrapper is compiled before the failing module, so
        # that module carries the first definitions of reserve() and its
        # allocation helpers only. Constructing from a sized iterable then
        # reaches the reserve() call inside the pythonized __init__, and
        # that wrapper is the one the JIT cannot compile.
        child = (
            "import cppjit\n"
            "v0 = cppjit.gbl.std.vector['int']()\n"
            "cppjit.cppdef('extern int undefined_fn_q();"
            " void first_r() { std::vector<int> v; undefined_fn_q();"
            " v.reserve(4); }')\n"
            "try:\n"
            "    cppjit.gbl.first_r()\n"
            "except BaseException as e:\n"
            "    print('POISONED', type(e).__name__)\n"
            "try:\n"
            "    v = cppjit.gbl.std.vector['int'](range(10))\n"
            "    print('CONSTRUCTED', len(v))\n"
            "except BaseException as e:\n"
            "    print('CAUGHT', type(e).__name__, str(e).replace('\\n', ' | '))\n"
            "print('EXIT_OK')\n"
        )
        proc = self._run_child(child)

        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert "EXIT_OK" in proc.stdout
        assert "CppInterOp CRASH DETECTED" not in proc.stderr
        assert "POISONED RuntimeError" in proc.stdout, (proc.stdout, proc.stderr)
        caught = [l for l in proc.stdout.splitlines() if l.startswith("CAUGHT ")]
        assert caught, (proc.stdout, proc.stderr)
        assert "RuntimeError" in caught[0], caught[0]
        assert "reserve" in caught[0], caught[0]
