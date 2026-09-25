"""Stage files from a sibling repo into this package's tree via symlinks.

A pip wheel bundles its runtime resources inside the package directory, and the
libraries self-locate relative to their own __file__/dladdr path. Under Bazel
those resources live in *sibling* repos, out of reach of any package-relative
lookup. stage_files() re-creates the wheel layout in bazel-out/runfiles with
symlinks (no copies -- the CppInterOp solib is huge), so the same self-location
code works for wheels and Bazel alike.

Each file lands at <out_dir>/<path remainder after the first 'path_anchor/'
component>. E.g. srcs = [@cppinterop//:headers], path_anchor = "include",
out_dir = "python/cppjit/interop/include" maps
  .../cppinterop+/include/CppInterOp/CppInterOp.h
  -> python/cppjit/interop/include/CppInterOp/CppInterOp.h
and works for generated files (the tblgen'd .inc headers) too, since the
anchor is matched in short_path.
"""

def _stage_files_impl(ctx):
    outs = []
    marker = "/" + ctx.attr.path_anchor + "/"
    prefix = ctx.attr.path_anchor + "/"
    for f in ctx.files.srcs:
        sp = f.short_path
        idx = sp.find(marker)
        if idx >= 0:
            rel = sp[idx + len(marker):]
        elif sp.startswith(prefix):
            rel = sp[len(prefix):]
        else:
            fail("stage_files: no '%s/' component in %s" % (ctx.attr.path_anchor, sp))
        out = ctx.actions.declare_file(ctx.attr.out_dir + "/" + rel)
        ctx.actions.symlink(output = out, target_file = f)
        outs.append(out)
    return [DefaultInfo(
        files = depset(outs),
        runfiles = ctx.runfiles(files = outs),
    )]

stage_files = rule(
    implementation = _stage_files_impl,
    doc = "Symlink srcs into out_dir, keyed by the path remainder after path_anchor.",
    attrs = {
        "srcs": attr.label_list(allow_files = True, mandatory = True),
        "out_dir": attr.string(mandatory = True),
        "path_anchor": attr.string(mandatory = True),
    },
)
