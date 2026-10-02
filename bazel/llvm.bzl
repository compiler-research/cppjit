"""Module extension generating the @llvm repo from a local LLVM/Clang tree.

The tree is selected (highest precedence first) by the LLVM_DIR env var, else
the root module's llvm.config(path=...) tag. No version is pinned: whatever tree
is pointed at is used as-is.

Header layout: an LLVM *install* tree merges every header under include/, but a
*build* tree splits them across four roots -- source llvm/include and
clang/include (siblings of the build dir) plus generated <obj>/include and
<obj>/tools/clang/include. We discover all that exist (via llvm-config), symlink
each under a stable name, and record them in LLVM_INCLUDE_DIRS so consumers get
the right -isystem set for either tree shape.
"""

_BUILD_HEADER = """\
load(":cc_toolchain.bzl", "cppjit_cc_toolchain")
load("@@rules_cc+//cc:defs.bzl", "cc_library")

package(default_visibility = ["//visibility:public"])

filegroup(name = "all_files", srcs = glob([
    "bin/**", "lib/**", "libexec/**", "share/**", {inc_globs}
], allow_empty = True))

filegroup(name = "lib_files", srcs = glob(["lib/**"], allow_empty = True))

filegroup(name = "include", srcs = glob([{inc_globs}], allow_empty = True))

# Clang's builtin (resource-dir) headers alone. cppjit stages these into its own
# tree so the interpreter gets a pinned -resource-dir instead of probing the host.
filegroup(name = "clang_resource_files", srcs = glob([
    "lib/clang/*/include/**",
], allow_empty = True))

# A ready-to-use header library: textual_hdrs (LLVM ships .def/.inc and many
# non-self-contained headers, so skip strict standalone-compile validation) plus
# `includes` to emit the -isystem flags for every discovered header root.
cc_library(
    name = "headers",
    textual_hdrs = glob([{inc_globs}], allow_empty = True),
    includes = [{inc_dirs}],
)

exports_files(["bin/clang", "bin/clang++", "bin/llvm-config"])

# The single, centralized C++ toolchain: builds everything with this LLVM tree's
# clang. cppjit_bazel registers @llvm//:cc_toolchain so all consumers inherit it
# with no per-repo CC/CXX wiring. See cc_toolchain.bzl for the captured config.
cppjit_cc_toolchain(name = "cc_toolchain")
"""

# Generated cc_toolchain.bzl in the @llvm repo: a macro wrapping the stock
# unix cc_toolchain_config with this tree's clang, captured builtin include
# dirs, and the ABI-critical flags LLVM was built with. {placeholders} filled in
# by the repo rule.
_CC_TOOLCHAIN_BZL = '''\
"""Centralized clang C++ toolchain for the cppjit stack (generated)."""

load("@bazel_tools//tools/cpp:unix_cc_toolchain_config.bzl", "cc_toolchain_config")
load("@@rules_cc+//cc:defs.bzl", "cc_toolchain")

_BUILTIN_INCLUDES = {builtin_includes}
_ABI_FLAGS = {abi_flags}

def cppjit_cc_toolchain(name):
    cc_toolchain_config(
        name = name + "_config",
        cpu = "k8",
        compiler = "clang",
        toolchain_identifier = "cppjit-clang",
        host_system_name = "local",
        target_system_name = "local",
        target_libc = "local",
        abi_version = "local",
        abi_libc_version = "local",
        cxx_builtin_include_directories = _BUILTIN_INCLUDES,
        tool_paths = {tool_paths},
        # ABI-critical flags applied to EVERY C++ TU (incl. third-party gtest)
        # so std:: layout / assertion mode is consistent across the .so
        # boundary. Per-target codegen flags (-fno-exceptions etc.) stay in
        # cppjit_bazel//:defs.bzl BASE_COPTS where they can be overridden.
        compile_flags = ["-fPIC"],
        cxx_flags = ["-std={cxx_std}"],
        link_flags = {link_flags},
        extra_flags_per_feature = {{}},
        opt_compile_flags = [],
        dbg_compile_flags = [],
        conly_flags = [],
        # C++ runtime + libm, as the stock unix toolchain links by default.
        link_libs = ["-lstdc++", "-lm"],
        opt_link_flags = [],
        unfiltered_compile_flags = _ABI_FLAGS,
        coverage_compile_flags = [],
        coverage_link_flags = [],
        # --start-lib/--end-lib is an lld/gold extension; GNU ld rejects it. Only
        # claim support when we actually link with lld (see has_lld below).
        supports_start_end_lib = {supports_start_end_lib},
    )

    cc_toolchain(
        name = name + "_cc",
        toolchain_config = ":" + name + "_config",
        all_files = ":all_files",
        compiler_files = ":all_files",
        dwp_files = ":empty",
        linker_files = ":all_files",
        objcopy_files = ":all_files",
        strip_files = ":all_files",
        supports_param_files = 1,
    )

    native.filegroup(name = "empty", srcs = [])

    native.toolchain(
        name = name,
        toolchain = ":" + name + "_cc",
        toolchain_type = "@bazel_tools//tools/cpp:toolchain_type",
        exec_compatible_with = ["@platforms//cpu:x86_64", "@platforms//os:linux"],
        target_compatible_with = ["@platforms//cpu:x86_64", "@platforms//os:linux"],
    )
'''

def _strip_lib_name(fname):
    """libLLVMCore.a -> LLVMCore; mirror llvm-config --libnames stripping."""
    name = fname
    if name.startswith("lib"):
        name = name[len("lib"):]
    for suffix in (".a", ".so", ".dylib"):
        if name.endswith(suffix):
            return name[:-len(suffix)]
    return name

# Candidate header roots, as (repo-relative symlink name, absolute path) given
# the llvm-config includedir and obj-root. An install tree collapses several to
# the same realpath (deduped below) or leaves them absent.
def _header_root_candidates(includedir, obj_root):
    # includedir is <src>/llvm/include for a build tree, <prefix>/include for an
    # install tree; its grandparent is the source/prefix root.
    src_root = includedir + "/../.."
    return [
        ("include", obj_root + "/include"),  # generated llvm
        ("clang_include", obj_root + "/tools/clang/include"),  # generated clang
        ("llvm_src_include", includedir),  # source llvm
        ("clang_src_include", src_root + "/clang/include"),  # source clang
    ]

def _llvm_repo_impl(rctx):
    # Three ways to point at the LLVM tree, highest precedence first:
    #   1. llvm.config(llvm_config_label = "@some_llvm//:bin/llvm-config") --
    #      reuse a tree a monorepo consumer already fetched as its own @llvm; no
    #      second download, and the path is resolved from the label so it's stable.
    #   2. LLVM_DIR env var.
    #   3. llvm.config(path = ...) string.
    # C++ standard the centralized toolchain compiles the stack at. Default
    # c++17 (matches the CMake build); a consumer building against a newer
    # libstdc++/interpreter overrides via llvm.config(cxx_std = "c++20"|...).
    cxx_std = rctx.attr.cxx_std or "c++17"

    if rctx.attr.llvm_config_label:
        # Resolving the label materializes the owning repo and gives its real
        # on-disk path; the tree root is the grandparent of bin/llvm-config.
        cfg = rctx.path(rctx.attr.llvm_config_label)
        path = str(cfg.dirname.dirname)
    else:
        path = rctx.os.environ.get("LLVM_DIR", rctx.attr.path)
    if not path:
        fail("No LLVM tree configured. Set llvm.config(llvm_config_label = ...) " +
             "to reuse an existing @llvm, the LLVM_DIR env var, or " +
             "llvm.config(path = ...).")

    llvm_config = rctx.path(path + "/bin/llvm-config")
    if not llvm_config.exists:
        fail("LLVM tree at '{}' has no bin/llvm-config. Point llvm_config_label, ".format(path) +
             "LLVM_DIR, or llvm.config(path = ...) at a valid LLVM build or install tree.")

    # Surface the non-header top-level dirs.
    for top in ("bin", "lib", "libexec", "share"):
        src = rctx.path(path + "/" + top)
        if src.exists:
            rctx.symlink(src, top)

    includedir = rctx.execute([llvm_config, "--includedir"]).stdout.strip()
    obj_root = rctx.execute([llvm_config, "--obj-root"]).stdout.strip()

    # Symlink each header root that exists, deduping by realpath so an install
    # tree (where several candidates resolve to the same dir) yields one entry.
    inc_dirs = []
    seen = {}
    for name, abspath in _header_root_candidates(includedir, obj_root):
        p = rctx.path(abspath)
        if not p.exists:
            continue
        real = str(p.realpath)
        if real in seen:
            continue
        seen[real] = True
        rctx.symlink(p, name)
        inc_dirs.append(name)

    if not inc_dirs:
        fail("@llvm: no header roots found under '{}'. Checked include/, ".format(path) +
             "tools/clang/include, and the llvm-config includedir.")

    inc_globs = ", ".join(['"{}/**"'.format(d) for d in inc_dirs])
    inc_dirs_lit = ", ".join(['"{}"'.format(d) for d in inc_dirs])
    rctx.file("BUILD.bazel", _BUILD_HEADER.format(
        inc_globs = inc_globs,
        inc_dirs = inc_dirs_lit,
    ))

    version = rctx.execute([llvm_config, "--version"]).stdout.strip()

    # Capture clang's own builtin include search dirs (libstdc++, the clang
    # resource dir, /usr/include) so the centralized toolchain declares exactly
    # what an autodetected clang would use -- matching the green build.
    clangxx = str(rctx.path(path + "/bin/clang++"))
    probe = rctx.execute([clangxx, "-E", "-x", "c++", "/dev/null", "-v"])
    builtin_includes = []
    collecting = False
    for line in probe.stderr.split("\n"):
        if "#include <...> search starts here:" in line:
            collecting = True
            continue
        if "End of search list." in line:
            collecting = False
            continue
        if collecting:
            d = line.strip()
            if d:
                builtin_includes.append(d)
    bindir = str(rctx.path(path + "/bin"))

    # Prefer lld iff this tree ships it: pass -fuse-ld=lld + -B<bindir> so the
    # clang driver finds it. An LLVM *build* tree has bin/ld.lld; many *install*
    # trees (e.g. the CI llvm-release recipe) omit it -- forcing -fuse-ld=lld
    # there fails ("invalid linker name"). When absent, emit no linker flag and
    # let clang use its default linker (the host's ld/gold, or lld if on PATH).
    # lld is only strictly required for an LTO/bitcode tree (which also ships it).
    has_lld = rctx.path(bindir + "/ld.lld").exists
    if has_lld:
        link_flags = ["-fuse-ld=lld", "-B" + bindir]
        ld_tool = bindir + "/ld.lld"
    else:
        link_flags = []
        ld_tool = "/usr/bin/ld"

    # --start-lib/--end-lib (which bazel emits when supports_start_end_lib) is an
    # lld/gold-only extension; GNU ld rejects it. Tie it to the linker we use.
    supports_start_end_lib = "True" if has_lld else "False"

    # The consuming code must compile with the SAME preprocessor defines LLVM
    # itself was built with (assertion mode, ABI, STDC macros); a mismatch
    # changes the layout/behavior of LLVM/Clang types and breaks the JIT at
    # runtime. Capture the -D flags from `llvm-config --cxxflags` verbatim.
    cxxflags = rctx.execute([llvm_config, "--cxxflags"]).stdout.replace("\n", " ").split(" ")
    llvm_defines = [f for f in cxxflags if f.startswith("-D") or f.startswith("-U")]

    # --link-static forces llvm-config to report the STATIC component archives +
    # their system deps even when the tree defaults to shared linkage (e.g. the
    # CI llvm-release recipe, which is built shared: plain --libnames there
    # returns just "libLLVM-22.so" and --libs "-lLLVM-22", which breaks our
    # self-contained static link with undefined refs). The flag is a no-op on a
    # static-default tree (a plain local build), so it's safe everywhere.

    # System libs the LLVM static libs were built against (e.g. -lz -lzstd when
    # LLVM has compression support, as a prebuilt consumer tree does). Captured from
    # llvm-config so the link adapts to whatever the tree needs; without these
    # the solib has undefined compressBound/ZSTD_* at dlopen.
    system_libs = [
        f
        for f in rctx.execute([llvm_config, "--link-static", "--system-libs"]).stdout.replace("\n", " ").split(" ")
        if f.startswith("-l")
    ]

    raw = rctx.execute([llvm_config, "--link-static", "--libnames", "all"]).stdout.replace("\n", " ")
    lib_names = [_strip_lib_name(n) for n in raw.split(" ") if n]

    # llvm-config never lists Polly; append it iff actually present in lib/.
    for polly in ("Polly", "PollyISL"):
        if rctx.path(path + "/lib/lib" + polly + ".a").exists or \
           rctx.path(path + "/lib/lib" + polly + ".so").exists:
            lib_names.append(polly)

    # Clang's static archives aren't covered by llvm-config; enumerate the
    # libclang*.a in lib/ (excluding the libclang-cpp dylib). The cppjit stack
    # links libclangCppInterOp.so self-contained from these + the LLVM
    # components, mirroring CMake's DISABLE_LLVM_LINK_LLVM_DYLIB build.
    clang_names = []
    for f in rctx.path(path + "/lib").readdir():
        bn = f.basename
        if bn.startswith("libclang") and bn.endswith(".a") and not bn.startswith("libclang-cpp"):
            clang_names.append(bn[len("lib"):-len(".a")])

    # If the LLVM static archives contain IR bitcode (a tree built with LTO,
    # like a prebuilt LTO consumer tree), mold/lld must load the LLVM linker plugin to
    # read those members; without it mold fails ("failed to load plugin").
    # Expose LLVMgold.so's repo-relative path iff it ships, so link helpers can
    # add --plugin only when needed. A non-LTO tree (no LLVMgold.so) leaves it
    # empty and the flag is omitted.
    gold_plugin = ""
    if rctx.path(path + "/lib/LLVMgold.so").exists:
        gold_plugin = "lib/LLVMgold.so"

    rctx.file("defs.bzl", ("LLVM_VERSION = {}\nLLVM_LIB_NAMES = {}\n" +
                           "CLANG_LIB_NAMES = {}\nLLVM_INCLUDE_DIRS = {}\n" +
                           "LLVM_DEFINES = {}\nLLVM_GOLD_PLUGIN = {}\n" +
                           "LLVM_SYSTEM_LIBS = {}\nLLVM_CXX_STD = {}\n" +
                           "LLVM_EXTRA_TEST_TAGS = {}\n").format(
        repr(version),
        repr(lib_names),
        repr(clang_names),
        repr(inc_dirs),
        repr(llvm_defines),
        repr(gold_plugin),
        repr(system_libs),
        repr(cxx_std),
        repr(rctx.attr.extra_test_tags),
    ))

    # ABI flags applied to every C++ TU by the centralized toolchain: the LLVM
    # build's own defines plus the visibility/codegen flags that must match the
    # libraries we interop with (a mismatch trips clang AST asserts / breaks the
    # JIT). Per-target flags like -fno-exceptions stay in BASE_COPTS.
    abi_flags = llvm_defines + [
        "-fno-semantic-interposition",
        "-fvisibility-inlines-hidden",
        "-fno-strict-aliasing",
        "-funwind-tables",
        "-fno-stack-protector",
    ]

    # Prefer this LLVM tree's llvm-* binutils, but fall back to the host's GNU
    # equivalents when absent: a full LLVM *build* tree ships them all, while a
    # minimal *install* tree (e.g. the CI llvm-release recipe) ships only clang +
    # a few tools. GNU ar/nm/objcopy/... are ABI-compatible with clang objects
    # for a normal (non-LTO) build; an LTO/bitcode tree, which needs llvm-ar to
    # read bitcode members, ships its own llvm-* anyway.
    def _tool(llvm_name, fallback):
        p = bindir + "/" + llvm_name
        return p if rctx.path(p).exists else fallback

    tool_paths = {
        "gcc": bindir + "/clang",
        "cpp": _tool("clang-cpp", "/usr/bin/cpp"),
        "ar": _tool("llvm-ar", "/usr/bin/ar"),
        "nm": _tool("llvm-nm", "/usr/bin/nm"),
        "ld": ld_tool,
        "as": bindir + "/clang",
        "objcopy": _tool("llvm-objcopy", "/usr/bin/objcopy"),
        "objdump": _tool("llvm-objdump", "/usr/bin/objdump"),
        "strip": _tool("llvm-strip", "/usr/bin/strip"),
        "gcov": _tool("llvm-cov", "/usr/bin/gcov"),
        "dwp": _tool("llvm-dwp", "/usr/bin/dwp"),
        "llvm-cov": _tool("llvm-cov", "/usr/bin/gcov"),
    }
    rctx.file("cc_toolchain.bzl", _CC_TOOLCHAIN_BZL.format(
        builtin_includes = repr(builtin_includes),
        abi_flags = repr(abi_flags),
        tool_paths = repr(tool_paths),
        link_flags = repr(link_flags),
        supports_start_end_lib = supports_start_end_lib,
        cxx_std = cxx_std,
    ))

_llvm_repo = repository_rule(
    implementation = _llvm_repo_impl,
    attrs = {
        "path": attr.string(),
        "llvm_config_label": attr.label(),
        "cxx_std": attr.string(),
        "extra_test_tags": attr.string_list(),
    },
    environ = ["LLVM_DIR"],
    local = True,
)

_config = tag_class(attrs = {
    "path": attr.string(
        doc = "Filesystem path to an LLVM build/install tree.",
    ),
    "llvm_config_label": attr.label(
        doc = "Label of a bin/llvm-config in an LLVM repo another module " +
              "already provides (e.g. \"@llvm//:bin/llvm-config\"). Reuses " +
              "that tree instead of fetching a second one; takes precedence " +
              "over path / LLVM_DIR. Resolved in the root module's context.",
    ),
    "cxx_std": attr.string(
        doc = "C++ standard the centralized clang toolchain compiles the " +
              "stack at, e.g. \"c++17\" (default), \"c++20\", \"c++2b\". A " +
              "consumer building against a newer libstdc++ / running the " +
              "interpreter at a higher standard should match it here.",
    ),
    "extra_test_tags": attr.string_list(
        doc = "Extra Bazel tags added to the stack's JIT tests (the cppinterop " +
              "and cppjit suites). Empty by default. A consumer running tests on " +
              "remote execution should set [\"no-remote-exec\"]: the tests " +
              "JIT-compile C++ in-process and need the host toolchain's libc " +
              "sysroot headers, which a hermetic remote action does not provide.",
    ),
})

def _llvm_impl(mctx):
    path = ""
    llvm_config_label = None
    cxx_std = ""
    extra_test_tags = []

    # Only the root module's config tag is honored.
    for mod in mctx.modules:
        if mod.is_root:
            for cfg in mod.tags.config:
                if cfg.path:
                    path = cfg.path
                if cfg.llvm_config_label:
                    llvm_config_label = cfg.llvm_config_label
                if cfg.cxx_std:
                    cxx_std = cfg.cxx_std
                if cfg.extra_test_tags:
                    extra_test_tags = cfg.extra_test_tags

    # Repo name is "cppjit_llvm", NOT "llvm": a monorepo consumer's CI derives
    # ASAN_SYMBOLIZER_PATH by globbing the output base for "*+llvm" expecting a
    # single LLVM repo. An extension repo named "llvm" canonicalizes to
    # "<module>++llvm+llvm", which ends in "+llvm" and collides with that glob,
    # breaking LeakSanitizer symbolization (and thus leak suppression) for the
    # whole build. "cppjit_llvm" canonicalizes to "<module>++llvm+cppjit_llvm",
    # which the glob does not match. Consumers still see it as @llvm via the
    # use_repo(llvm, llvm = "cppjit_llvm") alias in their MODULE.bazel.
    _llvm_repo(
        name = "cppjit_llvm",
        path = path,
        llvm_config_label = llvm_config_label,
        cxx_std = cxx_std,
        extra_test_tags = extra_test_tags,
    )

llvm = module_extension(
    implementation = _llvm_impl,
    tag_classes = {"config": _config},
)
