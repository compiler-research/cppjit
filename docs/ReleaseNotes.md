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

- ...

## Deprecated features

- ...

## Backwards incompatible changes

- ...

## Other changes

- `import cppjit` fails with an actionable `RuntimeError` when the C++
  standard headers do not parse, for example on a host without a C++
  toolchain. The failure used to surface later as
  `TypeError: 'std' is not a known C++ class`.
- `libcppjit` no longer exports the standard-library symbols it links
  statically from the build toolchain. A standard-library feature the
  host `libstdc++` cannot provide, such as `std::filesystem` on a GCC 8
  runtime, now fails with an error instead of crashing the process.
- `cppdef`, `cppexec`, `include`, `c_include` and `load_library` errors
  carry the compiler's diagnostic text. The message used to end after
  the generic prefix because the capture read `std::cerr` while clang
  and the JIT write to the standard error descriptor.
- A call whose JIT wrapper cannot be compiled, for example because the
  loaded `libstdc++` lacks a symbol the function needs, raises a
  `RuntimeError` carrying the JIT's report, whatever the return type.
  A `std::string` result used to come back empty and a `void` call
  returned silently.

## Contributors

Special thanks to everyone who contributed to this release:

- ...

<!-- Contributors since the previous release, with commit counts, in
alphabetical order:
 git log --pretty='%an' v0.1.0a1..HEAD | sort | uniq -c
-->
