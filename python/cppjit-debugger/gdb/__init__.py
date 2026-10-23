"""gdb extension for processes that run cppjit.

Load it in gdb with ``source <this directory>/cppjit_gdb.py``; gdb also
auto-loads it with libcppjit.so if the package directory is in its
auto-load safe path. It adds:

- a frame filter (``cppjit-python``) that shows the Python frames of each
  thread between its native frames, with their arguments and locals;
- ``cppjit sources``: the C++ inputs that the JIT compiled from files;
- ``cppjit py-bt``: the Python backtrace of the selected thread;
- ``cppjit gil``: the thread that holds the GIL;
- a stop at each Python line breakpoint of ``cppjit.debugger``;
- FILE:LINE breakpoints that wait for the JIT to compile the line.

Only cpython.py is free of gdb imports.
"""

from __future__ import annotations


def install() -> None:
    from . import breakpoints, commands, frames, lines, values

    frames.install()
    values.install()
    commands.install()
    breakpoints.install()
    lines.install()
