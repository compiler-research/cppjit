"""gdb auto-loads this file with libcppjit.so; see debugger/gdb/cppjit_gdb.py."""

from __future__ import annotations

import os

_path = os.path.join(
    os.path.dirname(os.path.realpath(__file__)), "debugger", "gdb", "cppjit_gdb.py"
)
with open(_path) as _f:
    # Not "source": a nested source keeps this file's __file__.
    exec(
        compile(_f.read(), _path, "exec"),
        {"__file__": _path, "__name__": "cppjit_gdb_loader"},
    )
