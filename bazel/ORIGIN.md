# Runtime path resolution: self-location and the ${ORIGIN} token

The stack self-locates its own resources (bundled CppInterOp, the cpyrt API
headers, clang's builtin headers) relative to its load path: `libcppjit.so`
calls `dladdr` on itself and joins the baked relative spellings
(`interop/lib/...`, `interop/include`) onto that directory — see
`cppinterop_paths()` in `src/interop/interop_wrapper.cxx`. `staging.bzl` shows
how the Bazel tree recreates the wheel layout that makes this work. The only
paths a consumer must supply are its *own* toolchain args (e.g.
`--gcc-toolchain`) in `CPPINTEROP_EXTRA_INTERPRETER_ARGS`.

No installer knows its final absolute prefix at build time, and relative paths
break as soon as the process runs from a different cwd (a notebook kernel, a
tool run from $HOME). Args may therefore reference `${ORIGIN}` — the directory
of libcppjit.so itself, mirroring ELF rpath $ORIGIN semantics.

Bazel consumers: the solib dir sits three levels below the runfiles root, so
sibling repos resolve via ORIGIN_RUNFILES_ROOT (defs.bzl), e.g.
`"--gcc-toolchain=" + ORIGIN_RUNFILES_ROOT + "/" + repo_name("@gcc")`.
The expanded args carry literal `..` components; clang handles them fine.

`libcppjit.so` expands the token itself, in
`expandOriginInInterpreterArgs()` (`src/interop/interop_wrapper.cxx`): it
rewrites `CPPINTEROP_EXTRA_INTERPRETER_ARGS` before CreateInterpreter reads it.
A consumer therefore passes the token through verbatim and does not expand it.
A process that never loads `libcppjit.so` (a C++ client of CppInterOp alone)
gets no expansion, so it must write absolute or cwd-relative args.

# Standalone build

A fresh clone needs one thing from the host: an LLVM/Clang build or install
tree, given by `LLVM_DIR` (the same variable the CMake build takes, but pointed
at the tree root, not at `lib/cmake/llvm`).

```bash
git clone <this repo> && cd cppjit
LLVM_DIR=/path/to/llvm bazelisk test //...
```

CppInterOp comes from the pinned archive in `MODULE.bazel` — the commit
`CMakeLists.txt` pins as `CPPINTEROP_GIT_TAG` — so no sibling checkout is
needed. To build a local CppInterOp instead (the Bazel equivalent of CMake's
`CPPINTEROP_SOURCE_DIR`), swap the `archive_override` for the commented
`local_path_override` next to it.

`bazelisk build //:site_packages` writes the installable payload —
the `cppjit/` package with `libcppjit.so` and `cppjit/interop/` holding the bundled CppInterOp
library, headers and clang resource headers — with the same layout and the same
file set that `pip install .` puts into site-packages.
