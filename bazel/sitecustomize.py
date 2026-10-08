"""Startup fixups for the cppjit py_tests (imported by test/test_main.py).

1. Stale sysconfig include path: rules_python's standalone Python bakes a
   build-time INCLUDEPY ("/install/...") into sysconfig, so
   sysconfig.get_config_var("INCLUDEPY") points at a path that doesn't exist at
   runtime. Some cppjit tests pass that value to cppjit.add_include_path(), which
   errors on the missing dir. Repoint it at the real headers under
   sys.base_prefix.

2. Anchor the runfiles-relative library paths to an ABSOLUTE base. The test env
   sets LD_LIBRARY_PATH with "../<repo>+/..." segments, which only resolve when
   the process cwd is the runfiles _main dir. That holds for a local
   `bazel test`, but not in every environment (e.g. GitHub Actions, where the
   dlopen then fails / doubles the path). RUNFILES_DIR is an absolute path bazel
   always sets, and cwd == $RUNFILES_DIR/_main, so "../X" maps to
   "$RUNFILES_DIR/X"; rewrite the relative segments accordingly before
   `import cppjit` triggers the backend load.
"""

import os
import sys
import sysconfig

_real = os.path.join(
    sys.base_prefix,
    "include",
    "python" + sysconfig.get_python_version(),
)
if os.path.isdir(_real):
    sysconfig.get_config_vars()  # force the cache to populate
    sysconfig._CONFIG_VARS["INCLUDEPY"] = _real

# Rewrite cwd-relative "../" runfiles segments to absolute $RUNFILES_DIR paths.
_runfiles = os.environ.get("RUNFILES_DIR")
if _runfiles:

    def _anchor(value):
        parts = []
        for seg in value.split(os.pathsep):
            if seg.startswith("../"):
                seg = os.path.join(_runfiles, seg[len("../") :])
            parts.append(seg)
        return os.pathsep.join(parts)

    if "LD_LIBRARY_PATH" in os.environ:
        os.environ["LD_LIBRARY_PATH"] = _anchor(os.environ["LD_LIBRARY_PATH"])
