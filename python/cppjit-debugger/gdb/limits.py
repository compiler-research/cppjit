"""A limit on the children that gdb's DAP server reads for a value.

To count the children of a value, the DAP server lists all of them if the
pretty-printer has no num_children(). A container with garbage pointers,
for example a std::vector member before the constructor runs, can have
billions of children. gdb then reads them until it runs out of memory, and
the DAP server answers no more requests. The limit stops the count and the
list at CHILD_LIMIT.
"""

from __future__ import annotations

import itertools
from typing import Any, Callable, Iterator

import gdb
import gdb.printing

CHILD_LIMIT = 10000


class _Limited(gdb.ValuePrinter):
    def __init__(self, printer: Any) -> None:
        self._printer = printer
        self._count: int | None = None

    def to_string(self) -> Any:
        to_string = getattr(self._printer, "to_string", None)
        return to_string() if to_string else None

    def display_hint(self) -> str | None:
        hint = getattr(self._printer, "display_hint", None)
        return hint() if hint else None

    def children(self) -> Iterator[Any]:
        return itertools.islice(self._printer.children(), CHILD_LIMIT)

    def num_children(self) -> int:
        if self._count is None:
            self._count = sum(1 for _ in self.children())
        return self._count


def _limit(make: Callable[[gdb.Value], Any]) -> Callable[[gdb.Value], Any]:
    def make_visualizer(value: gdb.Value) -> Any:
        printer = make(value)
        if not hasattr(printer, "children") or (
            isinstance(printer, gdb.ValuePrinter) and hasattr(printer, "num_children")
        ):
            return printer
        return _Limited(printer)

    return make_visualizer


def install() -> None:
    # The DAP server gets each printer from gdb.printing.make_visualizer (gdb 14 or later).
    if hasattr(gdb, "ValuePrinter") and hasattr(gdb.printing, "make_visualizer"):
        gdb.printing.make_visualizer = _limit(gdb.printing.make_visualizer)
