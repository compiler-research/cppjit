"""Line breakpoints in code that the JIT has not compiled yet.

The JIT compiles an inline function, for example in a header, only when
the code first uses it. Until then the line of a FILE:LINE breakpoint has
no code, and gdb moves the breakpoint to the next line that has code, which
can be in a different function. This module disables such a location in
JIT code if the lines between have code. When the JIT compiles the
function, gdb sets the breakpoint again and finds the line itself.
"""

from __future__ import annotations

import re

import gdb

_SPEC = re.compile(r"^(?:-source\s+(.+?)\s+-line\s+(\d+)|(.+):(\d+))$")
_JIT_OBJFILE = "<in-memory@"
# The locations that this module disabled, as (breakpoint number, address).
_disabled: set[tuple[int, int]] = set()


def _requested_line(breakpoint: gdb.Breakpoint) -> int | None:
    found = _SPEC.match((breakpoint.location or "").strip())
    if not found:
        return None
    return int(found.group(2) or found.group(4))


def _is_filler(text: str) -> bool:
    text = text.strip()
    return not text or text.startswith(("//", "/*", "*")) or not text.strip("{}();")


def _moved_over_code(path: str, requested: int, actual: int) -> bool:
    """Whether lines REQUESTED to ACTUAL - 1 of PATH have code."""
    if actual < requested:
        return True
    try:
        with open(path, errors="replace") as f:
            lines = f.read().splitlines()
    except OSError:
        return False
    return not all(_is_filler(text) for text in lines[requested - 1 : actual - 1])


def _in_jit_code(location: gdb.BreakpointLocation) -> bool:
    objfile = gdb.current_progspace().objfile_for_address(location.address)
    return bool(objfile and (objfile.filename or "").startswith(_JIT_OBJFILE))


def _check(breakpoint: gdb.Breakpoint) -> None:
    if breakpoint.type != gdb.BP_BREAKPOINT or not breakpoint.is_valid():
        return
    requested = _requested_line(breakpoint)
    if requested is None:
        return
    for location in breakpoint.locations:
        key = (breakpoint.number, location.address)
        source = location.source
        if source is None or not _in_jit_code(location):
            continue
        wrong = source[1] != requested and _moved_over_code(
            location.fullname or source[0], requested, source[1]
        )
        if wrong and location.enabled:
            _disabled.add(key)
            location.enabled = False
        elif not wrong and key in _disabled:
            _disabled.discard(key)
            location.enabled = True


def _on_breakpoint(breakpoint: gdb.Breakpoint) -> None:
    try:
        _check(breakpoint)
    except (gdb.error, AttributeError, RuntimeError):
        pass  # gdb before 13 has no breakpoint locations.


def install() -> None:
    gdb.events.breakpoint_created.connect(_on_breakpoint)
    gdb.events.breakpoint_modified.connect(_on_breakpoint)
