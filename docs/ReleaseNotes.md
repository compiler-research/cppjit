# cppjit 0.1.0b1 Release Notes

This document contains the release notes for cppjit 0.1.0b1, an
automatic Python-C++ interoperability layer and bindings generator
built on CppInterOp and the LLVM compiler infrastructure. If you are
reading this file from a git checkout, it describes the *next* release,
not the current one. The notes of previously released versions are
archived on the
[releases page](https://github.com/compiler-research/cppjit/releases).

This release supports Python 3.12-3.14 and LLVM 21-22.

## Highlights

- ...

## New features

- Experimental debugger support, in builds with
  `-DCPPJIT_ENABLE_DEBUGGER_SUPPORT=ON` only. `CPPJIT_DEBUGGER_SUPPORT=1`
  starts a debug session: the JIT compiles with `-g -O0`, and the C++
  inputs go to files that gdb can show. A gdb extension
  (`cppjit/debugger/gdb`) shows mixed Python and C++ backtraces with the
  variables of both. `examples/vscode-gdb` adds Python breakpoints and
  steps between Python and C++ in VS Code, through gdb's DAP server.

## Deprecated features

- ...

## Backwards incompatible changes

- ...

## Other changes

- `import cppjit` raises a `RuntimeError` when the C++ standard headers do
  not parse, for example on a host without a C++ toolchain.

## Contributors

Special thanks to everyone who contributed to this release:

- ...

<!-- Contributors since the previous release, with commit counts, in
alphabetical order:
 git log --pretty='%an' v0.1.0a1..HEAD | sort | uniq -c
-->
