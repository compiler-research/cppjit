"""Shared Bazel rules for the cppjit stack: CppInterOp tablegen/buildinfo
generation, the c++ shim, and the cc_test / py_test macros. Each macro
translates the corresponding CMake recipe from the consumer repo.

Repo-mapping note: these macros expand in the CONSUMER package, so apparent
labels like "@cppinterop"/"@cppjit" resolve in the consumer's mapping (each
consumer bazel_deps on them). $(location ...)/$(execpath ...) Make-vars
likewise resolve against the target's own deps. cppjit_bazel itself never
resolves those names.
"""

load("@llvm//:defs.bzl", "LLVM_CXX_STD", "LLVM_EXTRA_TEST_TAGS")
load("//:defs.bzl", "BASE_COPTS", "CPPINTEROP_COPTS", "cppinterop_base_env", "cppjit_base_env", "is_main_repo", "repo_rloc")

# Explicit load instead of native.py_test: consumers may build with Starlark
# rule autoloads disabled, where the native symbol no longer exists.
load("@rules_python//python:defs.bzl", "py_test")
load("@@rules_cc+//cc:defs.bzl", "cc_library", "cc_shared_library", "cc_test")

# The JIT tests need a C++ toolchain at RUN time (clang-repl compiles in-process).
# Standalone uses the host's; a consumer without one (e.g. a hermetic CI) supplies it
# via two paired label_flags per module: :jit_cxx_data stages the headers/clang
# into runfiles, and :jit_cxx_interp_args carries the matching --gcc-toolchain /
# -stdlib++-isystem args as the CPPINTEROP_JIT_CXX_ARGS make-var. A make-var (not
# a MODULE.bazel/.bazelrc arg) because the runfiles-relative paths can only be
# formed in a .bzl, yet the upstream macros must stay host-based. _jit_cxx_env
# appends $(...) to the test env (empty for the default flag -> standalone
# unaffected); each repo adds its own flag to the tests' toolchains so $(...) resolves.
def _jit_cxx_env(env):
    existing = env.get("CPPINTEROP_EXTRA_INTERPRETER_ARGS", "")
    appended = "$(CPPINTEROP_JIT_CXX_ARGS)"
    merged = (existing + " " + appended) if existing else appended
    return env | {"CPPINTEROP_EXTRA_INTERPRETER_ARGS": merged}

# Numeric form of the toolchain C++ standard for BuildInfo's CMAKE_CXX_STANDARD
# (e.g. "c++17" -> "17", "c++2b" -> "2b"); cosmetic, shown by Cpp::GetBuildInfo().
_CXX_STD_NUM = LLVM_CXX_STD[len("c++"):] if LLVM_CXX_STD.startswith("c++") else LLVM_CXX_STD

# tablegen action -> output .inc file (lib/CppInterOp/CMakeLists.txt add_custom_command).
_TBLGEN_GENS = [
    ("-gen-cppinterop-api", "CppInterOpAPI.inc"),
    ("-gen-cppinterop-decl", "CppInterOpDecl.inc"),
    ("-gen-cx-cppinterop-decl", "CXCppInterOpDecl.inc"),
    ("-gen-cx-cppinterop-impl", "CXCppInterOpImpl.inc"),
]

def cppinterop_tblgen_inc_files():
    """Run :cppinterop-tblgen over CppInterOp.td to emit the 4 .inc headers."""
    td = "lib/CppInterOp/CppInterOp.td"
    for action, out in _TBLGEN_GENS:
        native.genrule(
            name = "gen_" + out.replace(".", "_"),
            srcs = [td, "lib/CppInterOp/CppInterOpAPI.td", "@llvm//:lib_files"],
            outs = ["include/CppInterOp/" + out],
            tools = [":cppinterop-tblgen", "@llvm//:bin/llvm-config"],
            # tblgen dlopen's LLVM; -I points at the .td's own dir for includes.
            cmd = ("LD_LIBRARY_PATH=$$(dirname $(execpath @llvm//:bin/llvm-config))/../lib " +
                   "$(location :cppinterop-tblgen) " +
                   "-I$$(dirname $(execpath " + td + ")) " + action + " " +
                   "$(execpath " + td + ") -o $@"),
        )

def cppinterop_buildinfo_inc():
    """configure_file(BuildInfo.inc.in -> include/CppInterOp/BuildInfo.inc)."""
    native.genrule(
        name = "gen_buildinfo_inc",
        srcs = ["lib/CppInterOp/BuildInfo.inc.in"],
        outs = ["include/CppInterOp/BuildInfo.inc"],
        tools = ["@llvm//:bin/clang"],
        cmd = _BUILDINFO_CMD.replace("@@CXX_STD_NUM@@", _CXX_STD_NUM),
    )

# Map COMPILATION_MODE to CMAKE_BUILD_TYPE; parse clang/llvm version from
# `clang --version`; fill uname for the target triple. Done inline in bash so
# the genrule has no extra script file to ship.
_BUILDINFO_CMD = r"""
case "$(COMPILATION_MODE)" in
  opt) BT=Release ;;
  dbg) BT=Debug ;;
  *) BT=RelWithDebInfo ;;
esac
VER=$$($(execpath @llvm//:bin/clang) --version | sed -n '1s/.*version \([0-9.]*\).*/\1/p')
SYSNAME=$$(uname -s)
SYSPROC=$$(uname -m)
sed -e "s|@CMAKE_BUILD_TYPE@|$$BT|g" \
    -e "s|@CMAKE_CXX_STANDARD@|@@CXX_STD_NUM@@|g" \
    -e "s|@CMAKE_CXX_COMPILER_ID@|Clang|g" \
    -e "s|@CMAKE_CXX_COMPILER_VERSION@|$$VER|g" \
    -e "s|@LLVM_PACKAGE_VERSION@|$$VER|g" \
    -e "s|@CPPINTEROP_USE_CLING@|OFF|g" \
    -e "s|@LLVM_USE_SANITIZER@||g" \
    -e "s|@CMAKE_SYSTEM_NAME@|$$SYSNAME|g" \
    -e "s|@CMAKE_SYSTEM_PROCESSOR@|$$SYSPROC|g" \
    -e "s|@CPPINTEROP_CMAKE_INVOCATION@||g" \
    $(location lib/CppInterOp/BuildInfo.inc.in) > $@
"""

def cppinterop_cxx_shim():
    """Emit an executable cxx_shim/c++ forwarding to llvm's clang++.

    Cpp::DetectSystemCompilerIncludePaths popen()'s `c++`, which is absent in
    hermetic sandboxes; this shim on PATH satisfies it.
    """
    native.genrule(
        name = "gen_cxx_shim",
        outs = ["cxx_shim/c++"],
        tools = ["@llvm//:bin/clang++"],
        # rlocationpath = the canonical runfiles path of llvm's clang++.
        cmd = (
            "echo '#!/bin/bash' > $@ && " +
            "echo 'exec \"$$RUNFILES_DIR/" +
            "$(rlocationpath @llvm//:bin/clang++)\" \"$$@\"' >> $@ && " +
            "chmod +x $@"
        ),
        executable = True,
    )

def _cppinterop_test_common(name, srcs, extra_copts, extra_deps, data, env, includes):
    return dict(
        name = name,
        srcs = srcs + ["@cppinterop//:headers", "@cppinterop//:internal_headers"],
        # @llvm//:headers supplies the LLVM/Clang -isystem roots; tests include
        # them transitively via Utils.h / CppInterOp.h.
        deps = ["@googletest//:gtest", "@llvm//:headers"] + extra_deps,
        copts = extra_copts,
        data = data + [
            "@cppinterop//:data",
            "@cppinterop//:solib",
            "@cppinterop//:test_solib",
            "@cppinterop//:cxx_shim/c++",
            "@llvm//:bin/clang++",
            # Consumer-supplied JIT C++ toolchain (libstdc++ headers /
            # clang) staged into runfiles; empty by default (host).
            "@cppinterop//:jit_cxx_data",
        ],
        env = env,
        includes = includes,
    )

def cppinterop_cc_test(name, srcs, extra_copts = [], extra_deps = [], extra_dynamic_deps = [], data = [], env = {}, extra_tags = []):
    """A CppInterOp gtest linking clangCppInterOp via dynamic_deps.

    extra_tags adds to the LLVM tags, so a consumer can select or exclude a
    test with --test_tag_filters.
    """

    # This macro only expands in @cppinterop, so when that is the main repo
    # (standalone build) the @cppinterop paths are self-references; let them
    # resolve to the runfiles root rather than ../cppinterop+ (which only exists
    # when cppinterop is an external dep).
    cppinterop_is_self = is_main_repo(native.repository_name())
    cxx_shim_dir = repo_rloc("@cppinterop", cppinterop_is_self) + "/cxx_shim"
    base = _cppinterop_test_common(
        name = name,
        srcs = srcs,
        # upstream main.cpp provides main(), so gtest (not gtest_main).
        extra_copts = CPPINTEROP_COPTS + extra_copts,
        extra_deps = extra_deps,
        data = data,
        env = _jit_cxx_env(cppinterop_base_env(cppinterop_is_self) | {"PATH": cxx_shim_dir + ":/usr/bin:/bin"} | env),
        includes = ["include", "unittests/CppInterOp"],
    )

    # Link ONLY the solib (it carries LLVM) -- static LLVM too would give a second
    # copy of LLVM's globals and the in-process clang AST asserts. -rdynamic exports
    # the test's own symbols so the JIT can resolve template bodies instantiated in
    # the test TU (e.g. instantiation_in_host<int>).
    cc_test(
        dynamic_deps = ["@cppinterop//:solib"] + extra_dynamic_deps,
        linkopts = ["-ldl", "-lpthread", "-rdynamic"],
        tags = LLVM_EXTRA_TEST_TAGS + extra_tags,
        # Resolves $(CPPINTEROP_JIT_CXX_ARGS) in the env (empty by default).
        toolchains = ["@cppinterop//:jit_cxx_interp_args"],
        **base
    )

def cppinterop_dispatch_cc_test(name, srcs):
    """DispatchTests: dlopen's clangCppInterOp, so NO solib/llvm linkage."""
    cppinterop_is_self = is_main_repo(native.repository_name())
    cppinterop_rloc = repo_rloc("@cppinterop", cppinterop_is_self)
    cxx_shim_dir = cppinterop_rloc + "/cxx_shim"
    base_env = cppinterop_base_env(cppinterop_is_self)
    base = _cppinterop_test_common(
        name = name,
        srcs = srcs,
        # No LLVM link: the tests dlopen the solib at runtime.
        extra_copts = BASE_COPTS,
        extra_deps = [],
        # solib arrives via dlopen at runtime; the common data already ships it.
        data = [],
        # CPPINTEROP_BIN_DIR is the artifacts prefix the tests dlopen
        # <prefix>/lib/libclangCppInterOp.so from; the solib's shared_lib_name
        # gives it that lib/ component under runfiles, whose root is the cwd.
        env = _jit_cxx_env(base_env | {
            "CPPINTEROP_BIN_DIR": cppinterop_rloc,
            "PATH": cxx_shim_dir + ":/usr/bin:/bin",
            "LD_LIBRARY_PATH": base_env["LD_LIBRARY_PATH"] + ":lib",
        }),
        includes = ["include", "unittests/CppInterOp"],
    )
    cc_test(
        tags = LLVM_EXTRA_TEST_TAGS,
        # Resolves $(CPPINTEROP_JIT_CXX_ARGS) in the env (empty by default).
        toolchains = ["@cppinterop//:jit_cxx_interp_args"],
        **base
    )

def cppjit_test_dict_sos(sokeys):
    """Per key: a cc_library + a cc_shared_library producing test/cpp/<key>Dict.so.

    Mirrors cppjit's test/Makefile, which builds <key>Dict.so next to the
    test sources under test/cpp/.
    """
    for key in sokeys:
        cc_library(
            name = key + ".a",
            srcs = ["test/cpp/" + key + ".cxx"],
            hdrs = native.glob(["test/cpp/*.h"]),
            # The test dictionaries have intentional unused/leaky-dtor patterns;
            # demote so a consumer toolchain with -Werror still builds.
            copts = [
                "-fPIC",
                "-Wno-error=unused-but-set-parameter",
                "-Wno-unused-but-set-parameter",
                "-Wno-error=delete-non-abstract-non-virtual-dtor",
                "-Wno-delete-non-abstract-non-virtual-dtor",
            ],
            deps = ["@rules_python//python/cc:current_py_cc_headers"],
        )
        cc_shared_library(
            name = key + "Dict.so",
            deps = [key + ".a"],
            shared_lib_name = "test/cpp/" + key + "Dict.so",
        )

# The py_test source set shared by every cppjit suite: the test module itself
# plus the helpers every module imports.
def _py_test_srcs(name):
    return [
        "test/" + name + ".py",
        "test/support.py",
        "test/test_main.py",
        "test/assert_interactive.py",
    ]

def cppjit_py_test(name, sokeys = [], extra_env = {}):
    """A cppjit pytest driven through test/test_main.py.

    The pytest dependency comes from the @cppjit//:pytest label_flag: the
    standalone build's hermetic hub by default, or whatever a consumer points it
    at (e.g. @cppjit//:ambient_pytest when the interpreter already ships pytest,
    as on a consumer's conda toolchain).
    """
    dict_sos = [k + "Dict.so" for k in sokeys]

    base_env = cppjit_base_env()

    # test/cpp resolves under the cppjit repo, which is the runfiles cwd
    # standalone but external/<cppjit>+ when a consumer runs the suite.
    test_dir = repo_rloc("@cppjit", is_main_repo(native.repository_name())) + "/test/cpp"
    py_test(
        name = name,
        main = "test/test_main.py",
        tags = LLVM_EXTRA_TEST_TAGS,
        srcs = _py_test_srcs(name),
        # test_main.py forwards argv to pytest.main(); point it at this test's
        # own file via $(rootpath) so the path resolves whether cppjit is the main
        # repo (standalone) or an external dep (a consumer's external/cppjit+/).
        args = ["$(rootpath test/" + name + ".py)"],
        # The test modules do `import support` etc.; put test/ on sys.path.
        imports = ["test"],
        deps = [
            "@cppjit//:lib",
            "@cppjit//:pytest",
            "@cppjit_bazel//:sitecustomize",
        ],
        data = dict_sos + [
            "@cppjit//:cxxh",
            "@cppjit//:data",
            "@llvm//:all_files",
            # Consumer-supplied JIT C++ toolchain (libstdc++ headers / clang)
            # staged into runfiles; empty by default (host).
            "@cppjit//:jit_cxx_data",
        ],
        # No library/include path env for cppjit's own resources: the stack
        # self-locates all of them from libcppjit.so's own directory, so every
        # test exercises that path.
        env = _jit_cxx_env(base_env | {
            "PYTHONUNBUFFERED": "1",
            "CPPJIT_TEST_SKIP_MAKE": "True",
            # Some tests load secondary dicts by bare name and the loader
            # force-includes the matching header, so put test/cpp on both the
            # library and the interpreter include paths.
            "LD_LIBRARY_PATH": base_env["LD_LIBRARY_PATH"] + ":" + test_dir,
            "CPLUS_INCLUDE_PATH": test_dir,
        } | extra_env),
        # Resolves $(CPPINTEROP_JIT_CXX_ARGS) in the env (empty by default).
        toolchains = ["@cppjit//:jit_cxx_interp_args"],
    )

def cppjit_selflocation_py_test(name):
    """The self-location property test: no lib/include path env vars, no
    CPLUS_INCLUDE_PATH, no LD_LIBRARY_PATH, cwd changed away from the runfiles
    root before import. Everything must resolve from libcppjit.so's own
    location, through the layout :data stages beside it."""
    py_test(
        name = name,
        main = "test/test_main.py",
        tags = LLVM_EXTRA_TEST_TAGS,
        srcs = _py_test_srcs(name),
        args = ["$(rootpath test/" + name + ".py)"],
        imports = ["test"],
        deps = [
            "@cppjit//:lib",
            "@cppjit//:pytest",
            "@cppjit_bazel//:sitecustomize",
        ],
        data = [
            "@cppjit//:data",
            "@llvm//:all_files",
            # Consumer-supplied JIT C++ toolchain (libstdc++ headers / clang)
            # staged into runfiles; empty by default (host).
            "@cppjit//:jit_cxx_data",
        ],
        env = _jit_cxx_env({
            "PYTHONUNBUFFERED": "1",
            "CLING_STANDARD_PCH": "none",
        }),
        # Resolves $(CPPINTEROP_JIT_CXX_ARGS) in the env (empty by default).
        toolchains = ["@cppjit//:jit_cxx_interp_args"],
    )
