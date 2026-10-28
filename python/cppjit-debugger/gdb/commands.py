"""The cppjit prefix command of gdb."""

from __future__ import annotations

import glob
import os
import re
from typing import Callable

import gdb

from . import breakpoints, cpython, frames, inferior


def _first_code_line(path: str) -> str:
    try:
        with open(path, errors="replace") as f:
            for line in f:
                if line.strip() and not line.startswith("#line"):
                    return line.strip()
    except OSError:
        pass
    return ""


def _inputs() -> list[str]:
    directory = inferior.source_dir()
    if directory is None:
        raise gdb.GdbError(
            "CPPINTEROP_JIT_SOURCE_DIR is not set in the process; start it with CPPJIT_DEBUGGER_SUPPORT=1"
        )
    return sorted(
        glob.glob(os.path.join(directory, "input_*.cpp")), key=os.path.getmtime
    )


class CppjitCommand(gdb.Command):
    """Commands for debugging cppjit processes.

    cppjit sources, cppjit py-bt, cppjit py-step, cppjit gil, and cppjit up and
    down, which skip internal frames."""

    def __init__(self) -> None:
        super().__init__("cppjit", gdb.COMMAND_USER, prefix=True)


class SourcesCommand(gdb.Command):
    """List the C++ inputs that the JIT compiled from files.

    Usage: cppjit sources [REGEX]
    Without REGEX, show each input file and its first code line. With REGEX,
    show the matching lines as FILE:LINE, ready for "break FILE:LINE"."""

    def __init__(self) -> None:
        super().__init__("cppjit sources", gdb.COMMAND_FILES)

    def invoke(self, arg: str, from_tty: bool) -> None:
        pattern = re.compile(arg.strip()) if arg.strip() else None
        for path in _inputs():
            name = os.path.basename(path)
            if pattern is None:
                print("%s  %s" % (name, _first_code_line(path)[:80]))
                continue
            with open(path, errors="replace") as f:
                for number, line in enumerate(f, 1):
                    if pattern.search(line):
                        print("%s:%d: %s" % (name, number, line.rstrip()))


class PyBacktraceCommand(gdb.Command):
    """Print the Python frames of the selected thread, most recent call last."""

    def __init__(self) -> None:
        super().__init__("cppjit py-bt", gdb.COMMAND_STACK)

    def invoke(self, arg: str, from_tty: bool) -> None:
        try:
            segments = inferior.python_segments()
        except cpython.Unsupported as exc:
            raise gdb.GdbError("No Python state: %s" % exc)
        frames = [frame for segment in segments for frame in segment]
        if not frames:
            print("No Python frames in this thread.")
            return
        print("Traceback (most recent call last):")
        for frame in reversed(frames):
            path = inferior.python_file(frame.filename)
            print('  File "%s", line %s, in %s' % (path, frame.line, frame.name))
            text = _line_text(path, frame.line)
            if text:
                print("    " + text)


def _line_text(path: str, line: int) -> str:
    try:
        with open(path, errors="replace") as f:
            for number, text in enumerate(f, 1):
                if number == line:
                    return text.strip()
    except (OSError, TypeError):
        pass
    return ""


class GilCommand(gdb.Command):
    """Show which thread holds the GIL.

    A thread stopped while it holds the GIL blocks all other Python threads of
    the process, also when other threads are free to run (non-stop mode)."""

    def __init__(self) -> None:
        super().__init__("cppjit gil", gdb.COMMAND_STATUS)

    def invoke(self, arg: str, from_tty: bool) -> None:
        try:
            holder = inferior.runtime().gil_holder()
        except cpython.Unsupported as exc:
            raise gdb.GdbError("No Python state: %s" % exc)
        if holder is None:
            print("This is a free-threaded CPython: it has no GIL.")
        elif holder == 0:
            print("No thread holds the GIL.")
        else:
            for thread in gdb.selected_inferior().threads():
                if thread.ptid[1] == holder:
                    print("Thread %d (LWP %d) holds the GIL." % (thread.num, holder))
                    return
            print("LWP %d holds the GIL." % holder)


class PyStepCommand(gdb.Command):
    """Continue to the next Python line of the selected thread.

    Usage: cppjit py-step [--arm] [into|over|out|return]
    "into" (the default) stops at the next line in user code, or in the
    first C++ function with debug information that a JIT call runs. "over"
    stops at the next line in this Python frame or a caller, "out" in a
    caller. In C++ code, "return" stops in the Python frame that called the
    C++ code, after the call. Lines in the standard library and in cppjit
    are not user code. With --arm, set the step but do not continue."""

    def __init__(self) -> None:
        super().__init__("cppjit py-step", gdb.COMMAND_RUNNING)

    def invoke(self, arg: str, from_tty: bool) -> None:
        words = arg.split()
        arm_only = "--arm" in words
        words = [w for w in words if w != "--arm"]
        mode = words[0] if words else "into"
        if len(words) > 1 or mode not in breakpoints.STEP_MODES:
            raise gdb.GdbError("Usage: cppjit py-step [--arm] [into|over|out|return]")
        breakpoints.request_step(mode)
        if not arm_only:
            gdb.execute("continue")


class _MoveCommand(gdb.Command):
    def __init__(
        self, name: str, step: Callable[[gdb.Frame], gdb.Frame | None]
    ) -> None:
        super().__init__("cppjit " + name, gdb.COMMAND_STACK)
        self._step = step

    def invoke(self, arg: str, from_tty: bool) -> None:
        count = int(arg) if arg.strip() else 1
        frame = gdb.selected_frame()
        while count > 0:
            frame = self._step(frame)
            if frame is None:
                raise gdb.GdbError("No more frames outside cppjit internals.")
            if not frames.is_internal_frame(frame):
                count -= 1
        frame.select()
        gdb.execute("frame")


def install() -> None:
    CppjitCommand()
    PyStepCommand()
    _MoveCommand("up", lambda f: f.older())
    _MoveCommand("down", lambda f: f.newer())
    SourcesCommand()
    PyBacktraceCommand()
    GilCommand()
