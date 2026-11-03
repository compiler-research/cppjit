# Debug JIT-compiled C++ from VS Code

`demo.py` compiles a C++ function with `cppjit.cppdef`, and the header
`demo.h` with `cppjit.include`, and calls them from Python. `demo.h` reads
`ust10y.json` with nlohmann/json, and fits a line to predict the next
close. The file has the 10-year US Treasury par yield for 30 days, from
treasury.gov (public domain). With this example you can stop in the C++ source, step through it,
see its variables, and see the Python lines that called it in the same
call stack. `Histogram` comes from `lib`, a prebuilt library without
its source.

The debugger support is experimental. It can change or go away, and it is
not in the default build.

[AGENTS.md](AGENTS.md) has notes for a coding agent or a person that
continues the work on the debugger support.

## Requirements

- A cppjit built with `-DCPPJIT_ENABLE_DEBUGGER_SUPPORT=ON`. Without it,
  cppjit has no `cppjit.debugger` package, no gdb extension and no
  debugger hooks.
- Linux, and gdb 16 or later (for its DAP server). Tested with gdb 16.3.
- CPython 3.13 or later for the Python frames in the call stack: the gdb
  extension reads CPython's `_Py_DebugOffsets` table, so CPython does not
  need debug information.
- A CppInterOp that supports `CPPINTEROP_JIT_SOURCE_DIR`, for breakpoints
  by file and line in `cppdef` code. Breakpoints by function name work
  without it.
- The nlohmann/json header, for example from the `nlohmann-json3-dev`
  package, or as `nlohmann/json.hpp` in this directory.
- A C++ compiler for `lib/build.sh` (`g++`, or `CXX=clang++`).
- A ptrace scope that lets gdb debug its child processes
  (`/proc/sys/kernel/yama/ptrace_scope` 0 or 1; attach needs 0).

## Steps

1. Install the example extension. It has no build step:

   ```sh
   ln -s "$PWD/extension" ~/.vscode/extensions/cppjit-gdb
   ```

   Then reload VS Code.

2. Build the example library: `lib/build.sh`.

3. Open this directory in VS Code. In `.vscode/launch.json`, set `program`
   to a Python interpreter that can import cppjit.

4. Set a breakpoint. Click in the gutter of `demo.py`, for example at the
   `stats = ...` line in `report`. Or, in Run and Debug, add a function breakpoint
   `summarize` (Breakpoints, `+`). Or click in the gutter of `demo.h`, for
   example in `fit_line`. Or run the demo once, then open the
   C++ input from the source directory and click in the gutter:

   ```sh
   grep -l summarize "${TMPDIR:-/tmp}/cppjit-debug-$(id -u)"/input_*.cpp
   ```

   The file name is a hash of the code, so the breakpoint stays valid for
   the next runs until the code changes.

5. Start "cppjit: demo.py (gdb)". VS Code stops at the breakpoint. The
   call stack shows the C++ frames of `summarize`, then `[py] report` and
   `[py] <module>`. Click a `[py]` frame to open `demo.py` at the line
   that called the C++ code.

Before the JIT compiles the code, the Debug Console can show "No source
file named demo.h". gdb then makes the breakpoint pending, and sets it
when the JIT compiles the code.

`CPPJIT_DEBUGGER_SUPPORT=1` in the launch configuration makes cppjit
compile with `-g -O0` and write each C++ input to a file.
`CPPINTEROP_JIT_SOURCE_DIR` selects another directory. Python and C output are line buffered in a
debug session, so the output shows before each stop.

## Python breakpoints

gdb cannot bind a breakpoint in a `.py` file, so `extension/dap-proxy.js`
sits between VS Code and gdb. It answers the `setBreakpoints` requests for
Python files itself and writes the lines to a JSON file. The launch request
passes that file to the process in `CPPJIT_PY_BREAKPOINTS`. `cppjit.debugger`
then uses `sys.monitoring` (Python 3.12 or later) to call the native
function `cppjit_debug_break_python` before each of these lines, and the
cppjit gdb extension stops there and shows the Python line as the top
frame. The process reads the file again when it changes, so breakpoints
can be added while it runs.

The same works without VS Code: write the JSON file
(`{"/path/demo.py": [28]}`), set `CPPJIT_PY_BREAKPOINTS` to its path, and
run under gdb with the extension loaded.

## Stepping and internal frames

The call stack hides the internal frames by default: the cppjit and
CppInterOp runtime, CPython, the C runtime, and the `__jc_*` call
wrappers that CppInterOp generates. If a stop is in internal code, the
top frame stays, marked `[internal]`. Set `"internalFrames": "show"` in
the launch configuration to see and step through all frames. Or, at a
stop, type `set cppjit internal-frames show` (or `hide`) in the Debug
Console.

- At a Python line, Step Over, Step Into and Step Out step through Python
  lines. The proxy turns them into `cppjit py-step` and a continue. Step
  Over at a `return`, and Step Out, stop in the caller's line.
- Step Into at a Python line that calls C++ stops at the first line of
  the C++ function, if it has debug information (JIT code has it). For a
  constructor, it stops in the constructor.
- In C++ code, the steps are gdb's own. A step that leaves the outermost
  C++ function stops at the Python line that called it, not in the
  wrappers.

In the gdb CLI, `cppjit py-step [into|over|out]` steps through Python
lines and into C++, `cppjit py-step return` goes from C++ code to the
Python line that called it, `cppjit up` and `cppjit down` skip internal frames, and
`set cppjit internal-frames show` shows all frames in `bt`.

### Source for internal frames

An internal frame shows source only if its library has debug information.
gdb finds the source files from the paths in the debug information. If
the files are in a different location, use `directory` or
`set substitute-path` in gdb.

- cppjit and CppInterOp: configure cppjit with
  `-DCMAKE_BUILD_TYPE=RelWithDebInfo` or `Debug`. CppInterOp uses the
  same build type.
- CPython: gdb needs the debug symbols of the Python that runs the
  program, and its source:
  - A CPython that you build from source has debug symbols by default.
    Run it from its build tree, or add `directory <source tree>`.
  - A distribution Python keeps its debug symbols in a separate package,
    for example `dnf debuginfo-install python3` on Fedora and RHEL. With
    debuginfod (`set debuginfod enabled on`), gdb downloads the symbols
    and the source by itself.
  - If the symbols are in a different directory, add it with
    `set debug-file-directory <dir>:/usr/lib/debug`. If the source is in
    a different location, add `directory <source tree>`.
- Clang and LLVM: CppInterOp links them from the LLVM build that it
  uses. Their frames show source only if that LLVM build has debug
  information, for example `-DCMAKE_BUILD_TYPE=RelWithDebInfo` for LLVM.
  An LLVM with debug information is large, and it takes a long time to
  link. With a distribution LLVM, install its debug symbols as for
  CPython.

A rebuild or a gdbinit change takes effect in the next debug session.
VS Code does not need a reload.

## Breakpoints in headers

The JIT compiles an inline function, such as `fit_line` in
`demo.h`, only when the code first calls it. Until then, gdb finds no code
at a line in it. gdb then moves a breakpoint to the next line with code,
which can be in a different function, for example a constructor. The
cppjit gdb extension disables such a location if the lines between have
code. When the JIT compiles the function, gdb sets the breakpoint again at
the correct line.

## A library without its source

`lib` stands for a library that you have only as a header and a `.so`.
`lib/build.sh` builds `lib/libhistogram.so` with debug information, but
writes `/build/histogram` as its source directory, as if the library came
from a different machine. `demo.py` loads it with `cppjit.load_library` and
includes `lib/histogram.h`.

- A stop in `Histogram::add` shows the function, its arguments and its
  variables: they come from the debug information.
- gdb does not find `histogram.cpp`. The proxy then removes the source of
  the frame, and VS Code shows its disassembly.
- To see the source, type `directory lib` in the Debug Console, or
  `set substitute-path /build/histogram lib`. The source shows at the next
  stop.

## Python variables

Each Python frame shows its arguments and its local variables. Module and
class bodies show the names in their namespace, without the `__dunder__`
names. The gdb extension reads the objects from the process memory, so
this also works at a C++ stop and in a core file:

- `int`, `float`, `bool`, `None`, `str` and `bytes` show like `repr()`.
- Lists, tuples and dicts show a short preview, and expand to their items.
- A C++ object that cppjit returns to Python shows as the C++ object,
  as in a C++ frame: it expands to its fields. An object in a smart
  pointer, such as `std::shared_ptr<T>`, shows as the `T` that it holds,
  or as the smart pointer if it is null. gdb's pretty-printers
  apply, for example to `std::vector`, if gdb loads them: gdb loads the
  libstdc++ printers only from a directory in its auto-load safe path
  (`add-auto-load-safe-path <libstdc++ directory>` in the gdbinit).
- Other objects show `<Type object at 0x...>`, and expand to their
  instance attributes.

In a Python frame, the proxy answers a hover, a watch or a console
expression that is a Python name, such as `point.x` or `items[0]`, from
these variables. In the gdb CLI, `bt full` shows them.

## Why gdb's DAP server

The extension starts `gdb -i dap` with the cppjit gdb extension loaded.
gdb's own DAP server uses gdb's frame filters for the call stack, so the
Python frames appear in VS Code without more code, and the smoke test
below can drive the same server. The Microsoft C/C++ extension talks to
gdb through MI instead. It can also show JIT code, but frame filters need
`-enable-frame-filters` there, and gdb 16 can hang in
`-stack-list-arguments` when a frame filter meets an optimized-out
artificial `this`.

`test/test_debugging.py::test_dap_session` is that smoke test. It drives
the same `gdb -i dap` command without VS Code: it sets a breakpoint in a
JIT input file, and checks the stack and the variables.

## Without VS Code

```sh
CPPJIT_DEBUGGER_SUPPORT=1 gdb -iex "source $(python -c 'import cppjit.debugger as d; print(d.gdb_script())')" \
    -iex 'set breakpoint pending on' -ex 'break -qualified summarize' -ex run --args python demo.py
```

`bt` shows the Python frames between the C++ frames.
`cppjit sources [REGEX]` lists the JIT inputs, or the lines that match
REGEX as `FILE:LINE`. `cppjit py-bt` prints the Python stack.
`cppjit gil` shows the thread that holds the GIL. gdb also loads the
extension by itself with `add-auto-load-safe-path <cppjit package
directory>`.

Use `break -qualified NAME` for a global function: `break NAME` also
matches each class member with that name, for example in LLVM.

## Limits

- Python variables are read only. There is no evaluation of Python
  expressions, only of names. Objects with `__slots__` show no
  attributes. C++ types that the debug information does not have show as
  Python objects.
- Python breakpoints and Python steps need a launch, not an attach.
- A value shows at most 10000 children. Thus a container with garbage
  pointers, such as a member before the constructor initializes it,
  cannot make gdb read without end.
- The proxy cancels an evaluate or a variables request after 5 s, and
  shows an error for it.
- A breakpoint or a step on a line that already ran can need up to 0.2 s
  of run time to take effect: CPython stops the line events of lines that
  had no breakpoint, and a thread turns them on again.
- In the CLI, a Python frame shows the address of the eval loop that runs
  it, and frames without debug information show `at LIBRARY` in place of
  `from LIBRARY` (gdb prints all frames that way when a frame filter is
  active).
