# Undo and failed inputs

In a notebook, a cell that fails to compile must not force a restart.
cppjit gives two guarantees:

- A failed `cppdef` or `cppexec` leaves the interpreter as it was before
  the call. Fix the code and run it again with the same names.
- `cppjit.undo()` withdraws the last successful `cppdef` or `cppexec`. Call
  it again to go back further.

```python
import cppjit

cppjit.cppdef("int answer() { return 41; }")
cppjit.undo()
cppjit.cppdef("int answer() { return 42; }")
assert cppjit.gbl.answer() == 42
```

`undo()` also drops the Python proxies that cppjit cached since that call,
so a name that you define again resolves to the new declaration. An object
that you made from a withdrawn class is not usable after the undo.

Use `cppjit.undo()`, not `cppjit.gbl.Cpp.Undo`. A raw `Cpp::Undo` counts
interpreter inputs, and cppjit adds inputs of its own between your cells.
cppjit routes `gbl.Cpp.Undo` around its JIT call wrapper, so that the
wrapper cannot withdraw itself.

## What is covered

The tests in `test/test_failed_input.py` show each case. `TestFAILED_INPUT`
covers failed inputs: parse and Sema errors, link failures, templates first
used by a failed input, an initializer that throws, and macros. `TestUNDO`
covers undo: variables, functions, classes, namespaces (new, reopened and
nested), redeclarations, enumerators, macros, include guards and
`#pragma once`.

Most of the rollback is in CppInterOp. See its
[Undo and failed inputs](https://github.com/compiler-research/CppInterOp/blob/main/docs/UndoAndFailedInputs.rst)
page for the mechanism and the upstream LLVM work.

## What is not covered

These tests are marked as expected failures, with the upstream work in the
reason:

| Case | Why |
|---|---|
| A CodeGen error, for example a duplicate mangled name, can crash the session | State in clang CodeGen; llvm#226285, #234493, #204152, #223305 |
| A function that fails to link on its first call stays broken after you define the missing symbol | ORC keeps the error; undo the cell and define the function again |
| Undo of a class definition after a forward declaration in an earlier cell | Private definition data in clang; fixed by llvm#218149 in LLVM 23.1.3 |
| A header that changed on disk after undo | clang caches file contents; llvm#182750 |

Side effects that already ran, such as memory, files and output, are not
undone.
