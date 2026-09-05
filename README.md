# cppjit: automatic Python/C++ interop and bindings

[![CI](https://github.com/compiler-research/cppjit/actions/workflows/ci.yml/badge.svg)](https://github.com/compiler-research/cppjit/actions/workflows/ci.yml)
[![Nightlies](https://github.com/compiler-research/cppjit/actions/workflows/nightly.yml/badge.svg)](https://github.com/compiler-research/cppjit/actions/workflows/nightly.yml)
[![Wheels](https://github.com/compiler-research/cppjit/actions/workflows/wheels.yml/badge.svg)](https://github.com/compiler-research/cppjit/actions/workflows/wheels.yml)
[![Python](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue)](https://github.com/compiler-research/cppjit)
[![License](https://img.shields.io/badge/license-BSD--3--Clause--LBNL-green)](https://spdx.org/licenses/BSD-3-Clause-LBNL.html)

cppjit embeds an interactive C++ JIT compiler in Python: write or import
C++ at runtime and use its functions, classes, and templates as if they
were Python. In contrast to other popular bindings libraries, there is no
wrapper code to write and no CMake build to set up: bindings materialize
automatically on demand, derived from the C++ declarations. Run-time
binding generation enables:

- **Detailed specialization** of each call at the point of use
- **Lazy loading** for reduced memory use in large-scale projects
- **Python-side cross-inheritance and callbacks** for working with C++
  frameworks
- **Run-time template instantiation**, so the binding surface never has to
  be enumerated ahead of time
- **Automatic object downcasting** and **exception mapping**
- **Interactive exploration** of C++ libraries from the Python prompt

cppjit supports user-developed C++ frameworks and third-party C++ libraries
from standard package managers, and lets you use them from your Python
application or build a Python-based DSL on top. cppjit is the successor
project of [cppyy](https://github.com/wlav/cppyy), rebuilt on
[CppInterOp](https://github.com/compiler-research/CppInterOp) and the
clang-repl C++ interpreter in LLVM. More details can be found in
[this presentation](https://indico.cern.ch/event/1471803/contributions/6968247/attachments/3283391/5868828/CppInterOp_CHEP2026.pdf)
at CHEP 2026.

### How it works

A CPython extension builds Python proxies for all C++ entities:
functions, classes, templates, and variables. C++ entities come with
Python ergonomics for constructors, operators, and data members. The
embedded JIT compiles the C++ they touch, lazily:

```python
import cppjit

cppjit.cppdef("""
struct Vec2 {
    double x, y;
    Vec2 operator+(const Vec2& o) const { return {x + o.x, y + o.y}; }
};""")

c = cppjit.gbl.Vec2(1, 2) + cppjit.gbl.Vec2(3, 4)
c.x, c.y                 # (4.0, 6.0)
```

Templates instantiate on demand, and STL containers behave like Python
containers:

```python
cppjit.cppdef("""
#include <algorithm>
template <typename T>
T largest(const std::vector<T>& xs) { return *std::max_element(xs.begin(), xs.end()); }
""")

v = cppjit.gbl.std.vector['int']([3, 1, 4, 1, 5])
cppjit.gbl.largest(v)    # 5; largest<int> is compiled at this call
len(v), list(v)          # vectors support len(), iteration, indexing
```

Python callables pass into C++ as function pointers:

```python
cppjit.cppdef("""
template <typename R, typename... U, typename... A>
R callme(R (*f)(U...), A &&...args) {
  return f(args...);
}""")

def callback(x: int, y: float) -> float:
    return x + y

cppjit.gbl.callme(callback, 123, 321.5)   # 444.5
```

NumPy arrays pass zero-copy; the C++ side works on the same buffer:

```python
import numpy as np
a = np.arange(6, dtype=np.float64)

cppjit.cppdef("void scale(double* xs, std::size_t n, double f) { while (n--) xs[n] *= f; }")
cppjit.gbl.scale(a, a.size, 10.0)
a                        # array([ 0., 10., 20., 30., 40., 50.]); same buffer, no copy
```

An installed C++ library binds at run time, with no binding code written
for it:

```python
import cppjit
cppjit.include('zlib.h')          # bring in the C++ declarations
cppjit.load_library('libz')       # load the symbols
cppjit.gbl.zlibVersion()          # '1.3'; call the library directly
```

CppInterOp enables the above examples by providing the API for runtime reflection and
driving Clang and the underlying JIT infrastructure.

### Use cases

- **Numerics and data science.** Move performance-critical code into C++
  in the same session.
- **Template-heavy API.** STL, Eigen, user templates: run-time instantiations
  occur lazily at call sites.
- **Existing C++ codebases.** Use production C++-only frameworks from Python
  without modifying them.
- **Framework for DSLs.** User-defined "pythonizations" help adapt the
  bindings into user-friendly Pythonic libraries with domain-specific
  interfaces.

### Install

Installing cppjit from a package manager like pip has one requirement:

- A C++ compiler (g++ or clang): the JIT compiles C++ against the
  host's standard library headers at run time

Building from source requires:

- LLVM/Clang development packages version 21 or 22
- Python 3.12+ with development headers
- CMake 3.21+ and a C++20 compiler: g++ 13+, or a Clang matching your LLVM
  major (e.g. Ubuntu's stock clang-18 fails against LLVM 21/22 headers)
- Network access on the first build (CppInterOp is cloned during the
  build) or a local build of CppInterOp (see developer instructions)

#### Install with pip

<details>
<summary><b>Ubuntu 24.04</b></summary>

```bash
sudo apt-get install -y git cmake make g++ python3-dev python3-venv python3-pip \
    wget lsb-release software-properties-common gnupg libzstd-dev libedit-dev
wget https://apt.llvm.org/llvm.sh && sudo bash llvm.sh 21
sudo apt-get install -y llvm-21-dev libclang-21-dev clang-21 libpolly-21-dev

python3 -m venv venv && source venv/bin/activate
git clone https://github.com/compiler-research/cppjit.git && cd cppjit
pip install -v . --config-settings=cmake.define.LLVM_DIR=/usr/lib/llvm-21/lib/cmake/llvm
```

</details>

<details>
<summary><b>macOS</b></summary>

```bash
brew install llvm@21 cmake ninja
python3 -m venv venv && source venv/bin/activate
git clone https://github.com/compiler-research/cppjit.git && cd cppjit
pip install -v . --config-settings=cmake.define.LLVM_DIR="$(brew --prefix llvm@21)/lib/cmake/llvm"
```

</details>

#### Development build (pip editable)

Editable install with a persistent build directory and incremental rebuilds:

```bash
pip install scikit-build-core
pip install --no-build-isolation -ve . \
    --config-settings=build-dir=build \
    --config-settings=cmake.define.LLVM_DIR=$LLVM_DIR
```

To co-develop both CppInterOp and cppjit, point the build at a local
checkout, which overrides the pinned tag:

```bash
git clone https://github.com/compiler-research/CppInterOp.git ../CppInterOp
pip install --no-build-isolation -ve . \
    --config-settings=build-dir=build-local \
    --config-settings=cmake.define.LLVM_DIR=$LLVM_DIR \
    --config-settings=cmake.define.CPPINTEROP_SOURCE_DIR=$PWD/../CppInterOp
```

This lets you add new CppInterOp API and use it from cppjit.

#### Development build (CMake)

Nothing is installed: the build tree is used in place, through
`PYTHONPATH`. CppInterOp is compiled and staged inside it, and the
Python package is assembled under `<build>/python`:

```bash
cmake -S cppjit -B build -DLLVM_DIR=$LLVM_DIR
cmake --build build -j
export PYTHONPATH=$PWD/build/python
```

A prebuilt CppInterOp, either an install prefix or a build directory,
is consumed in place through `CppInterOp_DIR` instead of being rebuilt:

```bash
cmake -S cppjit -B build -DLLVM_DIR=$LLVM_DIR \
    -DCppInterOp_DIR=$PWD/CppInterOp/build/lib/cmake/CppInterOp
```

#### Verify the install

Run from a directory outside the checkout; the in-tree `python/cppjit`
shadows the installed extension:

```bash
cd /tmp && python -c "import cppjit
cppjit.cppdef('int f(int x) { return x + 1; }')
print(cppjit.gbl.f(41))"   # 42
```

### Running the test suite locally

```bash
pip install -r requirements.txt
cd test
make -j4                          # builds the *Dict.so loaded for tests
python -m pytest -ra --tb=short
```
