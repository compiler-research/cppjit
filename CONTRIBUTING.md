# Contributing to cppjit

Thanks for your interest in cppjit. cppjit embeds an interactive C++ JIT
compiler in Python, built on
[CppInterOp](https://github.com/compiler-research/CppInterOp) and the
clang-repl interpreter in LLVM. It is the successor to
[cppyy](https://github.com/wlav/cppyy). The project is young and its APIs
still evolve, so contributions of all kinds are welcome.

This guide covers how to report problems and how to propose changes. For
building and installing cppjit, see the [README](README.md), which this
document does not repeat. Please be respectful and assume good faith in
issues and reviews.

## Ways to contribute

- Report bugs and request features on the
  [issue tracker](https://github.com/compiler-research/cppjit/issues).
- Improve the documentation, including this guide and the README.
- Fix a bug or add a feature and open a pull request.
- Review open pull requests, or help answer questions on issues.

Small, self-contained changes are the easiest to review and merge.

## Reporting bugs and requesting features

Open an issue on the
[tracker](https://github.com/compiler-research/cppjit/issues). A useful bug
report includes:

- A minimal, self-contained reproducer. A cppjit case usually reduces to a
  short script built on `cppjit.cppdef(...)` and a few calls.
- What you expected, and what happened instead, with the full error message
  or traceback.
- Your environment: the cppjit version
  (`python -c "import cppjit; print(cppjit.__version__)"`), the operating
  system, the Python version, and how cppjit was installed (a pip wheel, pip
  from source, or a development build, with the LLVM version used).

## Setting up a development environment

Follow the **Development build** sections of the [README](README.md). The
editable pip install with a persistent build directory gives incremental
rebuilds, and the CMake build stages the Python package under `<build>/python`
for use through `PYTHONPATH`.

cppjit pins a compatible CppInterOp commit in `CMakeLists.txt`
(`CPPINTEROP_GIT_TAG`). To work on both projects at once, clone CppInterOp
next to cppjit and pass `CPPINTEROP_SOURCE_DIR`, as the README describes. The
local checkout then overrides the pinned tag.

## Running the checks locally

A pull request has to pass the same checks that CI runs. Run them before you
push.

### Tests

The test suite builds small C++ dictionaries and then runs pytest:

```bash
pip install -r requirements.txt
cd test
make -j4                          # builds the *Dict.so libraries the tests load
python -m pytest -ra --tb=short
```

Tests must pass against the development build they import. If you use an
editable install, rebuild it after changing C++ sources, or the tests load a
stale extension.

### Formatting and lint

C++ sources are formatted with clang-format and Python with ruff. CI pins the
versions, so match them:

```bash
# C++ (src/ and test/cpp): the whole tree is checked, not just the diff
find src test/cpp -name '*.cxx' -o -name '*.h' | xargs clang-format-18 -i

# Python
pip install ruff==0.16.3
ruff check .
ruff format .
```

## Coding style

- **Python** follows the ruff configuration in `pyproject.toml`. The enabled
  rules are pyflakes and a subset of pycodestyle, plus import sorting. A few
  deliberate idioms are exempted there, for the package namespace and for the
  binding tests. Do not add blanket `noqa` comments to silence the linter.
- **C++** follows `.clang-format`. Keep the whole file formatted, since CI
  checks the tree as a whole rather than the diff.
- cppjit builds as C++20, and the CI matrix also exercises C++17 and C++23.
  Keep contributions compatible with all three.
- Mark an expected test failure with an in-file `xfail` rather than
  deselecting the test. `xfail_strict` is on, so an `xfail` that starts
  passing fails the suite and has to be removed.

## Commit messages

Keep history readable and bisectable:

- One logical change per commit, and one logical change per pull request.
- Write a single imperative subject line of at most 72 characters. A body is
  optional and rarely needed.
- Prefix the subject with the component in brackets. The tags in use map to
  the source tree:

  | tag | area |
  |-----|------|
  | `[cpyrt]` | the CPython runtime in `src/cpyrt` |
  | `[interop]` | the interop layer in `src/interop` |
  | `[python]` | the Python package in `python/cppjit` |
  | `[cmake]` / `[build]` | `CMakeLists.txt`, `cmake/`, and packaging |
  | `[ci]` | workflows and scripts under `.github` |
  | `[test]` | the test suite |
  | `[docs]` | documentation |

  For example: `[cpyrt] Fix leaked container reference in vector_iter`.

Do not put issue or pull-request references in the subject. A squash merge
appends the pull-request number automatically.

## Pull requests

1. Fork the repository and add the upstream remote:

   ```bash
   git remote add upstream https://github.com/compiler-research/cppjit.git
   ```

2. Branch from an up-to-date `upstream/main`, one branch per change. Rebase
   onto `upstream/main` if it moves while you work, rather than merging it in.

3. Push to your fork and open a pull request against `main`. Describe what
   changed and why, and state how you validated it (which configurations you
   built and tested).

Every pull request runs the **Test** workflow: the lint checks, plus a
build-and-test matrix across LLVM, Python, and C++ standard, including a
valgrind cell and a cling cell. Linux cells use the LLVM release recipe and
macOS cells use Homebrew LLVM. A pull request from a fork runs the same
matrix, minus the jobs that need repository credentials.

Two heavier flows are opt-in, through labels a maintainer can add:

- `test-nightly` runs the full nightly matrix on the pull request, including
  the C++17 and arm breadth cells. Re-apply the label for a fresh run.
- `build-wheels` builds the complete wheel set and tests each wheel.

Pull requests are squash-merged, so a clean single logical change per branch
keeps the merged history tidy. A reviewer will look at correctness, test
coverage, and that the change stays within its stated scope.

For contributions to the CI workflows, pin third-party actions by commit hash
and use version tags for first-party `actions/*`, matching the existing
workflows.

## Documentation and releases

- User-facing changes should add a note to `docs/ReleaseNotes.md`, which
  collects notes for the release under development.
- The release procedure itself is documented in
  [`docs/ReleaseProcess.md`](docs/ReleaseProcess.md).

## License

cppjit is distributed under the BSD-3-Clause-LBNL license. By contributing,
you agree that your contributions are licensed under the same terms.
