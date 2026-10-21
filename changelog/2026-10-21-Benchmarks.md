# 2026-10-21: Benchmarks of calls into C++

cppjit now has a benchmark suite for what calling C++ functions from Python
costs, and CI that catches pull requests that make those calls slower. It
lets work such as the new overload resolution
([#150](https://github.com/compiler-research/cppjit/pull/150)) and memory
management ([#114](https://github.com/compiler-research/cppjit/pull/114))
show its effect on call overhead.

## What is measured

`benchmarks/test_calls.py` counts the instructions that
[callgrind](https://valgrind.org/docs/manual/cl-manual.html) sees for a
single call. Instruction counts do not depend on the machine's load, so one
call per case is enough, and runs on different machines with the same
toolchain can be compared.

Every case is measured twice:

- `test_first_call`: the first call of a function, including cppjit's lazy
  setup (wrapper generation, template instantiation, overload resolution).
  It calls a never-called copy of the function (namespace `cold`), after
  warming up the process on another copy (`warmup`).
- `test_successive_call`: a call of an already-called function (`hot`).

The cases cover:

- every primitive type, passed by value, pointer, reference and const
  reference;
- strings (`std::string`, `std::string_view`, `const char*`);
- classes and enums, as several arguments mixing values, references and
  pointers;
- a non-templated overload set over classes and enums;
- a template instantiated with primitive types, deduced and explicit;
- overloaded templates instantiated with classes;
- overloaded higher order functions, templated and not, taking a Python
  callback.

The C++ functions only return their input, so the counts are cppjit's
overhead. They live in `benchmarks/cpp/`, and `make` builds them into
`benchmarks/cpp/callsDict.so` on the first run. Every result is checked, so
a case that resolves to the wrong overload fails instead of measuring the
wrong call.

## Running the benchmarks

```bash
cd benchmarks
./callgrind.sh counts.json                 # count everything (~2 min)
./callgrind.sh counts.json -- -k first     # only some cases
python -m pytest test_calls.py             # no counts, only check results
python report.py compare --base main.json --head counts.json
```

`callgrind.sh` needs valgrind and its headers (pass `CPPFLAGS=-I<dir>` if
they are not on the default include path). To make counts repeatable it
runs Python with ASLR off and a fixed environment. In docker, turning ASLR
off needs `--security-opt seccomp=unconfined`.

## CI

The new `.github/workflows/benchmark.yml` counts on Linux x86_64 with
Release builds, against the CppInterOp commit pinned in
`CPPINTEROP_GIT_TAG`, like the test workflow.

- A push to `main` publishes its counts to the `gh-pages` branch: charts of
  every benchmark over time (with
  [github-action-benchmark](https://github.com/benchmark-action/github-action-benchmark),
  under `/benchmarks/`) and `benchmarks/baseline.json`.
- A pull request counts only itself and compares against that baseline.
  `main` is counted again on the same runner when the baseline is missing,
  was counted with another toolchain (the `fingerprint`), or shows a
  regression, which this confirms. The job fails when a benchmark runs more
  than 5% more instructions than `main`, and the comparison is posted as a
  PR comment.

The charts need a `gh-pages` branch with GitHub Pages serving it.

## Known limitations

- Counts are repeatable for one build, but successive calls are sensitive
  to the process's memory layout: a change outside the measured call can
  move them by a few percent, enough to cross the 5% threshold.
- cppjit has no converter for `const wchar_t&`, `const char16_t&` and
  `const char32_t&`, so those cases are left out. A pointer to a char type
  is passed as a C string.
