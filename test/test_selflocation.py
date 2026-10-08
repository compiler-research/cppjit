import os


class TestSELFLOCATION:
    def test01_jit_from_foreign_cwd(self):
        """Import and JIT with cwd '/' and no path env vars: the stack must
        locate CppInterOp, the cpyrt API headers and clang's builtin headers
        from libcppjit.so's own location alone."""

        for var in (
            "CPPJIT_API_PATH",
            "CPLUS_INCLUDE_PATH",
            "LD_LIBRARY_PATH",
            "RUNFILES_DIR",
            "RUNFILES_MANIFEST_FILE",
        ):
            os.environ.pop(var, None)
        os.chdir("/")

        import cppjit

        cppjit.cppdef("int self_location_add(int a, int b) { return a + b; }")
        assert cppjit.gbl.self_location_add(20, 22) == 42
