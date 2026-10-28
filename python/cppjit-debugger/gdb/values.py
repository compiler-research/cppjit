"""Python objects as gdb values, for the variables of Python frames.

A Python object becomes an lvalue of a marker type at the object's address.
A pretty-printer shows it like its repr() and gives the items of lists,
tuples and dicts, and the attributes of other objects, as children. Thus
"bt full" and the Variables view of a DAP client can show them.

A cppjit proxy of a C++ object becomes the C++ object itself, if the debug
information has its type.
"""

from __future__ import annotations

import re
from typing import Iterator

import gdb

from . import cpython, inferior

_objects: set[int] = set()
_types: dict[str, gdb.Type | None] = {}


def _marker() -> gdb.Type:
    return gdb.lookup_type("unsigned long").volatile()


def _lookup_cpp_type(name: str) -> gdb.Type | None:
    try:
        return gdb.lookup_type(name)
    except gdb.error:
        pass
    if not name.endswith(">"):
        return None
    # gdb knows a template instance only by its full name, with the default arguments.
    pattern = re.escape(name[:-1]) + "[,>]"
    listing = gdb.execute("info types -q ^%s" % pattern, to_string=True)
    for found in re.findall(
        r"^\s*(?:\d+:\s*)?(?:struct |class |union )?(.+?);?$", listing, re.M
    ):
        if re.match(pattern, found):
            try:
                return gdb.lookup_type(found)
            except gdb.error:
                continue
    return None


def _cpp_type(name: str) -> gdb.Type | None:
    if name not in _types:
        _types[name] = _lookup_cpp_type(name)
    return _types[name]


def _pointer_to(val: gdb.Value, target: gdb.Type, depth: int = 8) -> gdb.Value | None:
    """The first field of VAL, searched depth first through bases and members, that is a
    TARGET*."""
    tp = val.type.strip_typedefs()
    if tp.code == gdb.TYPE_CODE_PTR:
        pointee = tp.target().strip_typedefs().unqualified()
        return val if pointee == target else None
    if tp.code != gdb.TYPE_CODE_STRUCT or not depth:
        return None
    for field in tp.fields():
        if not hasattr(field, "bitpos"):
            continue  # static
        found = _pointer_to(val[field], target, depth - 1)
        if found is not None:
            return found
    return None


def _cpp_value(address: int) -> gdb.Value | None:
    try:
        found = inferior.runtime().cpp_object(address)
    except (cpython.Unsupported, gdb.error):
        return None
    if not found:
        return None
    pointer, name, smart = found
    tp = _cpp_type(name)
    if smart is None:
        return gdb.Value(pointer).cast(tp.pointer()).dereference() if tp else None
    smart_tp = _cpp_type(smart[1])
    if smart_tp is None:
        return None
    holder = gdb.Value(smart[0]).cast(smart_tp.pointer()).dereference()
    # Show the object that the smart pointer holds, as Python does.
    held = _pointer_to(holder, tp.strip_typedefs().unqualified()) if tp else None
    try:
        if held is not None and int(held):
            return held.dereference()
    except gdb.error:
        pass
    return holder


def value(address: int) -> gdb.Value:
    """A gdb.Value for the Python object at ADDRESS."""
    cpp = _cpp_value(address)
    if cpp is not None:
        return cpp
    _objects.add(address)
    return gdb.Value(address).cast(_marker().pointer()).dereference()


class _Printer:
    def __init__(self, address: int, children: list[tuple[str, int]] | None) -> None:
        self._address = address
        self._children = children

    def to_string(self) -> str:
        try:
            return inferior.runtime().summary(self._address)
        except (cpython.Unsupported, gdb.error):
            return "<unreadable object at 0x%x>" % self._address


class _ParentPrinter(_Printer):
    def children(self) -> Iterator[tuple[str, gdb.Value]]:
        for name, address in self._children or ():
            yield name, value(address)


def _lookup(val: gdb.Value) -> _Printer | None:
    if val.address is None or str(val.type) != str(_marker()):
        return None
    address = int(val.address)
    if address not in _objects:
        return None
    try:
        children = inferior.runtime().children(address)
    except (cpython.Unsupported, gdb.error):
        children = None
    return _ParentPrinter(address, children) if children else _Printer(address, None)


class Variable:
    """A Python variable, in the SymValueWrapper form of frame decorators."""

    def __init__(self, name: str, address: int) -> None:
        self._name = name
        self._address = address

    def symbol(self) -> str:
        return self._name

    def value(self) -> gdb.Value:
        return value(self._address)


def variables(frame: cpython.PyFrame) -> tuple[list[Variable], list[Variable]]:
    """The arguments and the locals of FRAME, a cpython.PyFrame, as two lists of Variable."""
    try:
        arguments, local = inferior.runtime().variables(frame)
    except (cpython.Unsupported, gdb.error):
        return [], []
    return [Variable(*v) for v in arguments], [Variable(*v) for v in local]


def install() -> None:
    gdb.pretty_printers.append(_lookup)
    gdb.events.cont.connect(_forget)


def _forget(event: gdb.ContinueEvent) -> None:
    # The addresses are valid only until the process runs again, and new JIT code can add types.
    _objects.clear()
    _types.clear()
