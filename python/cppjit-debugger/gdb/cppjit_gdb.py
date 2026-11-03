"""Load the cppjit gdb extension: ``source`` this file in gdb."""

from __future__ import annotations

import importlib.util
import os
import sys


def _load() -> None:
    name = "cppjit_gdb_extension"
    if name in sys.modules:
        return
    # Load the directory under its own name: importing the cppjit package would start a JIT in gdb.
    here = os.path.dirname(os.path.realpath(__file__))
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(here, "__init__.py"), submodule_search_locations=[here]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    module.install()


_load()
