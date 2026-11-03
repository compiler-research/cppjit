"""Mixed Python and C++ backtraces.

The frame filter puts the Python frames that a run of CPython's eval loop
executes in the place of its native _PyEval_EvalFrameDefault frame. Thus
each JIT-compiled C++ frame is shown below the Python line that called it.
The native frame stays available as an elided frame.

By default, the filter also hides internal frames: the cppjit and CppInterOp
runtime, CPython, the C runtime, the JIT call wrappers, and native code
without line information. If the stop itself is in internal code, the top
frame stays, marked "[internal]". "set cppjit internal-frames show" shows
all frames.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Iterator

import gdb
from gdb.FrameDecorator import FrameDecorator

from . import cpython, inferior, values

FILTER_NAME = "cppjit-python"
_EVAL_LOOP = "_PyEval_EvalFrameDefault"
PYTHON_BREAK = "cppjit_debug_break_python"
DEBUG_MODULE = os.path.join("cppjit", "debugger", "__init__.py")
INTERNAL_MARK = "[internal] "
WRAPPER_PREFIX = "__jc_"
_RUNTIME = re.compile(
    r"^(libcppjit|libclangCppInterOp|libpython|libc[.-]|ld-linux|libffi|libstdc\+\+|libgcc_s)"
)
_PACKAGE = os.sep + "cppjit" + os.sep


class InternalFramesParameter(gdb.Parameter):
    """Whether backtraces show the internal frames of cppjit, CppInterOp and CPython."""

    set_doc = "Show or hide the internal frames of cppjit, CppInterOp and CPython."
    show_doc = "Show whether backtraces show internal frames."

    def __init__(self) -> None:
        super().__init__(
            "cppjit internal-frames",
            gdb.COMMAND_STACK,
            gdb.PARAM_ENUM,
            ["hide", "show"],
        )
        self.value = "hide"

    def get_show_string(self, value: str) -> str:
        return "Internal cppjit frames: %s." % value


_parameter: InternalFramesParameter | None = None


def hiding() -> bool:
    return _parameter is None or _parameter.value == "hide"


class PythonFrame(FrameDecorator):
    """A Python frame, shown at the address of the eval loop that runs it."""

    def __init__(
        self, base: FrameDecorator, frame: cpython.PyFrame, last: bool
    ) -> None:
        super().__init__(base)
        self._base = base
        self._frame = frame
        self._last = last
        self._variables: tuple[list[values.Variable], list[values.Variable]] | None = (
            None
        )

    def function(self) -> str:
        return "[py] " + self._frame.name

    def address(self) -> int:
        # gdb's DAP server needs an address for each frame.
        return self._base.inferior_frame().pc()

    def filename(self) -> str:
        return inferior.python_file(self._frame.filename)

    def python_file(self) -> str:
        return self._frame.filename

    def line(self) -> int:
        return self._frame.line

    def _read_variables(
        self,
    ) -> tuple[list[values.Variable], list[values.Variable]]:
        if self._variables is None:
            self._variables = values.variables(self._frame)
        return self._variables

    def frame_args(self) -> list[values.Variable]:
        return self._read_variables()[0]

    def frame_locals(self) -> list[values.Variable]:
        return self._read_variables()[1]

    def elided(self) -> Iterator[FrameDecorator] | None:
        if not self._last or hiding():
            return None
        return iter([self._base])


class InternalFrame(FrameDecorator):
    """The top frame, in internal code."""

    def function(self) -> str:
        name = super().function()
        if isinstance(name, int):
            name = gdb.format_address(name)
        return INTERNAL_MARK + str(name)


def is_internal_frame(frame: gdb.Frame) -> bool:
    """Whether FRAME, a gdb.Frame, runs internal code."""
    try:
        name = frame.name() or ""
        if name.startswith(WRAPPER_PREFIX) or name == PYTHON_BREAK:
            return True
        if frame.find_sal().symtab is None:
            return True
        objfile = gdb.current_progspace().objfile_for_address(frame.pc())
    except (gdb.error, AttributeError):
        return False
    return bool(objfile and _RUNTIME.match(os.path.basename(objfile.filename)))


def _is_internal(item: FrameDecorator) -> bool:
    if isinstance(item, PythonFrame):
        return _PACKAGE in item.python_file()
    return is_internal_frame(item.inferior_frame())


def _hide_internal(items: Iterable[FrameDecorator]) -> Iterator[FrameDecorator]:
    first = True
    for item in items:
        if not _is_internal(item):
            yield item
        elif first:
            yield InternalFrame(item)
        first = False


def _is_eval_loop(frame: gdb.Frame) -> bool:
    try:
        return (frame.name() or "").startswith(_EVAL_LOOP)
    except gdb.error:
        return False


class PythonFrameFilter:
    def __init__(self) -> None:
        self.name = FILTER_NAME
        self.priority = 100
        self.enabled = getattr(gdb.frame_filters.get(self.name), "enabled", True)
        gdb.frame_filters[self.name] = self

    def filter(self, frames: Iterator[FrameDecorator]) -> Iterator[FrameDecorator]:
        try:
            segments = inferior.python_segments()
        except (cpython.Unsupported, gdb.error):
            segments = []
        if segments:
            frames = _skip_python_break(_merge(frames, segments))
        return _hide_internal(frames) if hiding() else frames


def _merge(
    frames: Iterable[FrameDecorator], segments: list[list[cpython.PyFrame]]
) -> Iterator[FrameDecorator]:
    pending = iter(segments)
    for item in frames:
        if _is_eval_loop(item.inferior_frame()):
            segment = next(pending, None)
            if segment:
                for i, frame in enumerate(segment):
                    yield PythonFrame(item, frame, i == len(segment) - 1)
                continue
        yield item


def _skip_python_break(items: Iterator[FrameDecorator]) -> Iterator[FrameDecorator]:
    """At a Python line breakpoint, start the stack at the Python line."""
    first = next(items, None)
    if first is None:
        return
    try:
        at_break = first.inferior_frame().name() == PYTHON_BREAK
    except gdb.error:
        at_break = False
    if not at_break:
        yield first
        yield from items
        return
    for item in items:
        if isinstance(item, PythonFrame) and not item.python_file().endswith(
            DEBUG_MODULE
        ):
            yield item
            yield from items
            return


def _parameter_prefix() -> None:
    if hasattr(gdb, "ParameterPrefix"):
        gdb.ParameterPrefix("cppjit", gdb.COMMAND_NONE)
        return
    for verb in ("set", "show"):
        gdb.Command("%s cppjit" % verb, gdb.COMMAND_NONE, prefix=True)


def install() -> None:
    global _parameter
    _parameter_prefix()
    _parameter = InternalFramesParameter()
    PythonFrameFilter()
