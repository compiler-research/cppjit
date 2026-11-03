# Notes for agents: the cppjit debugger support

These notes are for a coding agent (or a person) that continues the work on
source-level debugging of JIT-compiled C++. Read them with
[CONTRIBUTING.md](../../CONTRIBUTING.md) and the example's
[README](README.md), which describes the features
for users.

The support is experimental and opt-in. With
`CPPJIT_ENABLE_DEBUGGER_SUPPORT=OFF` (the default), the build must not change:
no `cppjit.debugger` package, no gdb extension, no hooks. Keep it that way.

## Map

| Part | Where |
|------|-------|
| Debug session: `-g -O0 -fstandalone-debug`, the source directory, line-buffered stdout | `src/interop/interop_wrapper.cxx` (`CPPJIT_WITH_DEBUGGER_SUPPORT`) |
| Native hooks that gdb breaks on: `cppjit_debug_break_python`, `cppjit_debug_enter_jit`, `cppjit_debug_leave_jit` | `src/interop/interop_wrapper.cxx` |
| Import of `cppjit.debugger` at module init | `src/cpyrt/cpyrtModule.cxx` |
| `cppjit.debugger`: source files, Python breakpoints and steps with `sys.monitoring`, `gdb_script()` | `python/cppjit-debugger/__init__.py` |
| gdb extension: one module for each concern, see each docstring | `python/cppjit-debugger/gdb/` |
| CPython state read from memory (`_Py_DebugOffsets`, frames, objects) | `gdb/cpython.py`, `gdb/inferior.py`, `gdb/values.py` |
| Mixed backtraces and hidden internal frames | `gdb/frames.py` |
| `cppjit` gdb commands (`py-step`, `py-bt`, `sources`, `up`, `down`, `gil`) | `gdb/commands.py` |
| Breakpoints in code that the JIT has not compiled yet | `gdb/lines.py`, `gdb/breakpoints.py` |
| A limit on the children of a value in DAP | `gdb/limits.py` |
| VS Code extension, and the DAP proxy that adds Python breakpoints and steps | `examples/vscode-gdb/extension/` |
| The demo | `examples/vscode-gdb/` |
| Tests (gdb CLI and DAP, with and without the proxy) | `test/test_debugging.py` |
| CI job | `debugger` in `.github/workflows/ci.yml` |

CppInterOp writes each interpreter input to a file in
`CPPINTEROP_JIT_SOURCE_DIR`, so that gdb can show the source and bind
`FILE:LINE` breakpoints in `cppdef` code. That part is in CppInterOp
(compiler-research/CppInterOp#1156). Until it is in the pinned CppInterOp,
build with `CPPINTEROP_SOURCE_DIR` set to a checkout of that branch.

## Set up

Requirements: Linux, gdb 16 or later (for its DAP server), CPython 3.13 or
later, `node` (for the DAP proxy tests and for VS Code), and an LLVM that
cppjit supports.

```bash
export LLVM_DIR=<your LLVM>/lib/cmake/llvm
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=RelWithDebInfo -DLLVM_DIR=$LLVM_DIR \
    -DCPPJIT_ENABLE_DEBUGGER_SUPPORT=ON \
    -DCPPINTEROP_SOURCE_DIR=$PWD/../CppInterOp   # a CppInterOp with #1156
cmake --build build -j
export PYTHONPATH=$PWD/build/python
```

`RelWithDebInfo` gives source for the cppjit and CppInterOp frames when you
show the internal frames. gdb loads the copy of the package in
`build/python/cppjit/debugger`. A build copies a change in
`python/cppjit-debugger` there; `--target cppjit-python-tree` copies only
the Python files.

gdb loads the libstdc++ pretty-printers, and on some systems
`libthread_db`, only from its auto-load safe path. Without the printers,
`std::vector` shows its raw fields. Add
`add-auto-load-safe-path <directory>` to `~/.config/gdb/gdbinit` for each.

## Run the demo

```bash
cd examples/vscode-gdb
lib/build.sh                      # libhistogram.so, without its source
# demo.h needs nlohmann/json: install it, or put nlohmann/json.hpp here
CPPJIT_DEBUGGER_SUPPORT=1 CPPINTEROP_EXTRA_INTERPRETER_ARGS=-std=c++20 python demo.py
```

An agent cannot click in VS Code. Use one of these:

- gdb in batch mode, with the extension loaded:

  ```bash
  CPPJIT_DEBUGGER_SUPPORT=1 CPPINTEROP_EXTRA_INTERPRETER_ARGS=-std=c++20 \
  gdb -batch -iex "source $(python -c 'import cppjit.debugger as d; print(d.gdb_script())')" \
      -iex 'set breakpoint pending on' \
      -ex 'break demo::Histogram::add' -ex run -ex bt -ex 'info locals' -ex 'print *this' \
      -ex 'directory lib' -ex list -ex kill --args python demo.py
  ```

- The DAP server, through the proxy, as VS Code uses it:
  `node extension/dap-proxy.js gdb -i dap -iex "source <gdb_script()>"`.
  `_Dap` in `test/test_debugging.py` is a small client to copy. Send
  `initialize`, `launch`, `setBreakpoints` or `setFunctionBreakpoints`,
  `configurationDone`, then wait for the `stopped` event and send
  `stackTrace`, `scopes` and `variables`.
- `set debug dap-log-file <file>` (in DAP mode) writes all DAP traffic of a
  VS Code session to a file. Use it to see what VS Code sends.

A person can follow the steps in the example's README to run the demo in
VS Code.

## Test

```bash
cd test
make -j4
python -m pytest -ra test_debugging.py
```

The gdb tests skip without gdb, the DAP tests without gdb 16, and the proxy
tests without `node`. They also skip if gdb cannot trace a process
(`ptrace_scope` 3, or a container that denies ptrace). For a bug,
write a test in `test_debugging.py` first and see it fail.

## Lessons

- gdb's DAP server answers one request at a time. A slow request blocks all
  of them, also the steps and the pause. `limits.py` stops the count of the
  children of a value at 10000 (garbage memory, for example a member before
  its constructor runs), and the proxy cancels an `evaluate` or `variables`
  request after 5 s.
- Do not call functions in the process from the extension. A pretty-printer,
  a frame filter or a value lookup can cause an inferior call, for example
  through the address of a thread-local variable. The DAP server reports the
  call as a stop with the reason "function call". Read memory instead.
- The Python state comes from memory through `_Py_DebugOffsets`, without
  CPython debug information, so it also works in a core file. Each CPython
  version can change the layouts. CPython 3.14 changed the owner of the
  entry frame and the layout of split dictionaries.
- The frame names have prefixes that the proxy uses: `[py] ` for a Python
  frame and `[internal] ` for an internal frame at the top of the stack.
- gdb moves a `FILE:LINE` breakpoint in an inline function that the JIT has
  not compiled yet to the next line with code. `lines.py` disables such a
  location until the JIT compiles the function.
- Clang leaves out the types that a library instantiates, such as
  `std::ifstream`, unless it has `-fstandalone-debug`. gdb then shows
  `<incomplete type>`.
- If the source file of a frame is missing, the proxy removes the source of
  the frame, so VS Code shows the disassembly and not an error.
- A gdb that is busy in a long Python call did not stop on SIGTERM. To stop
  a DAP gdb, close its stdin, or use SIGKILL.

## Open work

- **lldb.** Not started. These are the facts so far:
  - clang `-gdwarf-5 -gembed-source` puts the source text in the DWARF line
    table. gdb 16.3 ignores it. lldb 21 shows it (`source list`), also when
    the file is missing. A library without its source could then show source
    in lldb.
  - Questions to answer first: Does lldb see the JIT code through the GDB
    JIT interface on Linux, with its symbols and line tables? Do `FILE:LINE`
    breakpoints bind in the files in `CPPINTEROP_JIT_SOURCE_DIR`? How do the
    Python frames get into the stack? lldb has no frame filter API like
    gdb's. Options to look at: a DAP proxy in front of `lldb-dap` that
    changes `stackTrace`, or lldb's Python API.
  - The CPython reader (`cpython.py`) does not use the gdb API: it gets
    functions that read memory, from `inferior.py`. An lldb version of
    `inferior.py` can use the same reader.
- The limits in the example's README: Python variables are read only,
  Python breakpoints need a launch (not an attach), objects with `__slots__`
  show no attributes.
- Under gdb's `set environment`, libc's `environ` in the process did not
  have the variables that `/proc/PID/environ` had. `inferior.environment()`
  merges both. The cause is not known.
