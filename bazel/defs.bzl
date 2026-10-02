"""Shared copts, linkopts, and runtime env for the cppjit stack."""

load("@llvm//:defs.bzl", "CLANG_LIB_NAMES", "LLVM_GOLD_PLUGIN", "LLVM_INCLUDE_DIRS", "LLVM_LIB_NAMES", "LLVM_SYSTEM_LIBS", "LLVM_VERSION")

# Consumer repos aren't deps of cppjit_bazel, so Label() can't resolve them in
# this module's mapping; their single-version deps canonicalize to "name+". Map
# those literals and fall back to Label() for @llvm/anything else.
_CONSUMER_CANON = {
    "cppinterop": "cppinterop+",
    "cppjit": "cppjit+",
}

def repo_name(repo):
    return _CONSUMER_CANON.get(repo.lstrip("@"), None) or Label(repo).repo_name

# Build-time (execroot, e.g. -I) and runtime (runfiles) paths to an EXTERNAL dep
# repo. The external assumption breaks for a self-reference (e.g. CppInterOp's
# tests pointing at @cppinterop): as a main repo its files are at the root, not
# external/<name>+. repository_name() can't reveal another repo's canonical name,
# so the caller passes is_self=True for the one reference to its own module.
def repo_loc(repo, is_self = False):
    return "." if is_self else "external/" + repo_name(repo)

def repo_rloc(repo, is_self = False):
    return "." if is_self else "../" + repo_name(repo)

# ${ORIGIN} stands for the directory of libcppjit.so itself (ELF-$ORIGIN
# semantics -- no build-system content in the runtime code). Under Bazel that
# directory is always <runfiles root>/<repo>/python/cppjit (fixed by the solib's
# shared_lib_name), so THREE ups reach the runfiles root where sibling repos
# live. Consumers join this with repo_name() to write cwd-independent
# interpreter args:  ORIGIN_RUNFILES_ROOT + "/" + repo_name("@gcc") + "/..."
# libcppjit.so expands the token before CreateInterpreter reads the args, so
# pass it through verbatim; see ORIGIN.md.
ORIGIN_RUNFILES_ROOT = "${ORIGIN}/../../.."

# True when this module is built standalone (main repo, repository_name() == "@").
def is_main_repo(current_repo):
    return current_repo.lstrip("@") == ""

# Per-target codegen flags (ABI-critical flags live in the centralized toolchain).
# -fPIC is kept here, not relied on from the toolchain, so objects link into .so's
# even under a consumer toolchain that defaults cc_library to no-PIC (e.g. a
# monorepo consumer).
# -DNDEBUG is mandatory, not a -c opt nicety: the stack ships assert(0) stubs on
# live runtime paths (e.g. Interpreter::toString) that abort the process when a
# consumer builds -c dbg; the CMake/overlay build always sets NDEBUG, so we match.
BASE_COPTS = [
    "-fPIC",
    "-fno-exceptions",
    "-fno-rtti",
    "-ffunction-sections",
    "-fdata-sections",
    "-fno-common",
    "-O3",
    "-DNDEBUG",
]

CPPINTEROP_COPTS = BASE_COPTS + [
    "-DCPPINTEROP_USE_REPL",
    "-DLLVM_BINARY_DIR='\"" + repo_loc("@llvm") + "\"'",
    "-DCPPINTEROP_VERSION='\"0.1.0-bazel\"'",
]

def _llvm_L_rpath():
    return [
        "-L" + repo_loc("@llvm") + "/lib",
        "-Wl,-rpath," + repo_rloc("@llvm") + "/lib",
    ]

# LTO codegen parallelism for the bitcode-archive link. Fixed (not nproc) for
# reproducibility; 16 is plenty for the cppinterop link's module count.
_LTO_JOBS = 16

# LTO opt level for the bitcode-archive link governs the STACK FRAME SIZE of
# clang's own code inside libclangCppInterOp.so: at O0 its recursive constexpr
# evaluator gets fat frames and overflows the 8 MiB stack at JIT time on heavily
# templated code (e.g. Fastor). A per-consumer build setting (:lto_opt_level in
# CppInterOp/BUILD.bazel), not baked in: O0 keeps the standalone link fast, while
# a heavy-JIT consumer raises it (--@cppinterop//:lto_opt_level=2).
LTO_OPT_LEVELS = ["0", "1", "2", "3"]

# Upstream default: fast link. Insufficient for heavy JIT use; see above.
DEFAULT_LTO_OPT_LEVEL = "0"

def llvm_lto_opt_linkopts(level):
    """The -plugin-opt=O<level> flag for the LTO link, or [] for a non-LTO @llvm.

    Selected per build via the :lto_opt_level flag; emitted only when @llvm
    carries IR bitcode (LLVM_GOLD_PLUGIN set), where the level actually drives
    codegen. On a non-LTO tree the static link ignores it, so emit nothing.
    """
    if LLVM_GOLD_PLUGIN:
        return ["-Wl,-plugin-opt=O" + level]
    return []

# An LTO/bitcode @llvm tree (LLVM_GOLD_PLUGIN set) needs the LLVM plugin to read
# the archives; jobs=<n> keeps its codegen parallel (else serial = minutes). The
# -plugin-opt=O<n> level is appended separately via select() on :lto_opt_level.
# No-op on a non-LTO tree.
def _llvm_plugin():
    if LLVM_GOLD_PLUGIN:
        return [
            "-Wl,--plugin=" + repo_loc("@llvm") + "/" + LLVM_GOLD_PLUGIN,
            "-Wl,-plugin-opt=jobs=" + str(_LTO_JOBS),
        ]
    return []

# libclangCppInterOp.so links self-contained from the static clang+LLVM archives
# (no libclang-cpp.so dylib), mirroring CMake's DISABLE_LLVM_LINK_LLVM_DYLIB: one
# static copy of every symbol so nothing double-registers when it's dlopen'd.
# --start-group resolves the ~100 archives' mutual refs. The --system-libs
# (zlib/zstd) come separately via the :llvm_system_libs label_flag (so a hermetic
# consumer can ship its own), not from here.
def llvm_linkopts():
    return _llvm_L_rpath() + _llvm_plugin() + [
               "-Wl,--gc-sections",
               "-Wl,--start-group",
           ] + ["-l" + n for n in CLANG_LIB_NAMES] + \
           ["-l" + n for n in LLVM_LIB_NAMES] + [
        "-Wl,--end-group",
        "-ldl",
    ]

# For standalone LLVM tools (cppinterop-tblgen): the static component libs.
# libclang-cpp.so omits TableGen and some cl:: internals, so a tool using
# llvm::TableGen / RecordKeeper must link the components statically.
# tblgen does not run the JIT, so it always uses the fast default LTO level (no
# need for the per-consumer :lto_opt_level the solib carries).
def llvm_tblgen_linkopts():
    return _llvm_L_rpath() + _llvm_plugin() + \
           llvm_lto_opt_linkopts(DEFAULT_LTO_OPT_LEVEL) + \
           ["-l" + n for n in LLVM_LIB_NAMES]

# The LLVM --system-libs as bare -l flags (e.g. ["-lz", "-lzstd"]). Used as the
# linkopts of the DEFAULT :llvm_system_libs target, which resolves them from the
# host. A hermetic consumer (no host system libs, e.g. remote execution) swaps
# that target for a cc_library that ships the .so files directly.
#
# Wrapped in --no-as-needed/--as-needed: the references to these libs (ZSTD_*,
# inflate, xmlReadMemory) live INSIDE the static LLVM archives, not in the solib's
# own objects, and they're passed after the archive --end-group. Under the linker
# default (--as-needed) ld would drop them as "unused" and the solib would dlopen
# with undefined ZSTD_* symbols. --no-as-needed forces them in; restore the
# default afterwards so it doesn't leak to later libs.
def llvm_system_libs():
    if not LLVM_SYSTEM_LIBS:
        return []
    return ["-Wl,--no-as-needed"] + LLVM_SYSTEM_LIBS + ["-Wl,--as-needed"]

_LLVM_RLOC = repo_rloc("@llvm")

# clang-repl auto-detects its resource dir from the host binary's location,
# which fails under the test sandbox (the binary isn't beside lib/clang/<v>).
# Point it at @llvm's runfiles so the JIT finds stddef.h etc. Major version
# from LLVM_VERSION ("22.1.8" -> "22"). Also public: it names the versioned
# clang resource dir in the staged wheel layout.
LLVM_MAJOR = LLVM_VERSION.split(".")[0]

# How the cppinterop gtests find headers at JIT time: the clang builtins dir
# (lib/clang/<v>/include) plus every @llvm header root, on CPLUS_INCLUDE_PATH.
# Those tests pass no -resource-dir (it crashed the interpreter in early lexing),
# so the builtins must arrive this way. The cppjit py_tests are the opposite
# case: they DO get a pinned -resource-dir, from the staged bundled headers -- see
# cppjit_base_env below.
_CPLUS_INCLUDE_PATH = ":".join(
    [_LLVM_RLOC + "/lib/clang/" + LLVM_MAJOR + "/include"] +
    [_LLVM_RLOC + "/" + d for d in LLVM_INCLUDE_DIRS],
)

# Runtime env for the cppinterop unit tests. A function (not a constant) so the
# @cppinterop runfiles path self-corrects when cppinterop is its own main repo
# (standalone): the caller passes cppinterop_is_self = is_main_repo(
# native.repository_name()). @llvm is always external to cppinterop, so its
# paths never need the fixup.
def cppinterop_base_env(cppinterop_is_self = False):
    return {
        "CLING_STANDARD_PCH": "none",
        "LLVM_LIB_PATH": _LLVM_RLOC + "/lib",
        "LD_LIBRARY_PATH": _LLVM_RLOC + "/lib:" +
                           repo_rloc("@cppinterop", cppinterop_is_self) + "/lib",
        "CPLUS_INCLUDE_PATH": _CPLUS_INCLUDE_PATH,
    }

# Runtime env for the cppjit py_tests. libcppjit.so self-locates CppInterOp, the
# cpyrt API headers and clang's builtin headers from its own directory, and pins
# -resource-dir at that bundled copy. The two paths are mutually exclusive: reach
# the clang builtins through CPLUS_INCLUDE_PATH as well and the process dies
# during test collection WITH NO DIAGNOSTIC -- no error, no stack trace, no
# signal, just a truncated log and exit 1. So NO include path belongs here, only
# @llvm's and CppInterOp's shared-library dirs, which Bazel alone knows.
def cppjit_base_env():
    return {
        "CLING_STANDARD_PCH": "none",
        "LLVM_LIB_PATH": _LLVM_RLOC + "/lib",
        "LD_LIBRARY_PATH": _LLVM_RLOC + "/lib:" + repo_rloc("@cppinterop") + "/lib",
    }

# Carries the consumer's JIT interpreter args (--gcc-toolchain / -stdlib++-isystem,
# needed at RUN time; empty standalone where clang-repl autodetects the host) as
# the CPPINTEROP_JIT_CXX_ARGS make-var. The runfiles-relative paths can only be
# formed in a .bzl, not in static MODULE.bazel/.bazelrc text; the test macros
# expand $(...) into the env, and a label_flag swaps the empty default (paired
# with the :jit_cxx_data files flag). See _jit_cxx_env in rules.bzl.
def _jit_cxx_interp_args_impl(ctx):
    return [platform_common.TemplateVariableInfo({
        "CPPINTEROP_JIT_CXX_ARGS": ctx.attr.args,
    })]

jit_cxx_interp_args = rule(
    implementation = _jit_cxx_interp_args_impl,
    attrs = {
        "args": attr.string(
            doc = "Space-joined interpreter args, exposed as the " +
                  "CPPINTEROP_JIT_CXX_ARGS make-var. Empty by default (host).",
        ),
    },
)
