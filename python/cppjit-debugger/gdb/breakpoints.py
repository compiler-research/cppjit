"""Stops at Python line breakpoints, and steps from Python into C++.

cppjit.debugger calls the native function frames.PYTHON_BREAK when a Python
line in CPPJIT_PY_BREAKPOINTS is about to run, or at the end of a Python
step. An internal breakpoint there stops the process; the frame filter
then shows the Python line as the top frame.

During a step into, libcppjit calls ENTER_JIT with the Cpp::JitCall of each
call into JIT code. An internal breakpoint there finds the functions that
the JitCall's wrapper calls, and stops at the first one that runs.
"""

from __future__ import annotations

import re

import gdb

from . import cpython, frames, inferior
from .frames import DEBUG_MODULE, PYTHON_BREAK

ENTER_JIT = "cppjit_debug_enter_jit"
# The first argument register of each architecture.
_ARGUMENT = {"i386:x86-64": "rdi", "aarch64": "x0"}
_CALL = re.compile(r"\bcall\w*\s+(?:\*\S+\s+#\s+)?(0x[0-9a-f]+)")
_JUMP = re.compile(r"\bjmp\w*\s+\*\S+\s+#\s+(0x[0-9a-f]+)")
_LIBRARY = ("std::", "__gnu_cxx::", "__cxxabiv1::")
_breakpoints: dict[int, tuple[_PythonBreak, _EnterJitBreak]] = {}
# The gdb thread numbers that step into C++, and the breakpoints of the step.
_entering: set[int] = set()
_entries: list[_EntryBreak] = []


class _PythonBreak(gdb.Breakpoint):
    """Reports the Python line, not the internal breakpoint."""

    def __init__(self) -> None:
        super().__init__(PYTHON_BREAK, internal=True)
        self.silent = True

    def stop(self) -> bool:
        try:
            frames = [f for s in inferior.python_segments() for f in s]
        except (cpython.Unsupported, gdb.error):
            frames = []
        for frame in frames:
            if not frame.filename.endswith(DEBUG_MODULE):
                print(
                    "Python breakpoint, %s () at %s:%d"
                    % (frame.name, inferior.python_file(frame.filename), frame.line)
                )
                break
        return True


def _u64(address: int) -> int:
    return int.from_bytes(inferior.read(address, 8), "little")


def _function_block(pc: int) -> gdb.Block | None:
    try:
        block = gdb.block_for_pc(pc)
    except RuntimeError:
        return None
    while block is not None and block.function is None:
        block = block.superblock
    return block


def _resolve(target: int, architecture: gdb.Architecture) -> int:
    """The function that a call to TARGET runs: TARGET, or the target of its jump stub."""
    if _function_block(target) is None:
        found = _JUMP.search(architecture.disassemble(target)[0]["asm"])
        if found:
            target = _u64(int(found.group(1), 16))
    return target


def _called_functions(
    wrapper: int, architecture: gdb.Architecture
) -> list[tuple[str, int]]:
    """The user functions with debug information that the code at WRAPPER calls."""
    block = _function_block(wrapper)
    if block is None:
        return []
    found: list[tuple[str, int]] = []
    for instruction in architecture.disassemble(block.start, block.end - 1):
        call = _CALL.search(instruction["asm"])
        if not call:
            continue
        target = int(call.group(1), 16)
        if "*" in instruction["asm"].split("#")[0]:
            target = _u64(target)  # call through a pointer in memory
        target = _resolve(target, architecture)
        callee = _function_block(target)
        if callee is None or callee.function.symtab is None:
            continue
        name = callee.function.name
        if name.startswith(frames.WRAPPER_PREFIX) or target in [t for _, t in found]:
            continue
        found.append((name, target))
    users = [f for f in found if not f[0].startswith(_LIBRARY)]
    return users or found


class _EntryBreak(gdb.Breakpoint):
    """The first line of a C++ function that a Python step goes into."""

    def __init__(self, name: str, address: int, thread: int) -> None:
        try:
            super().__init__("-qualified " + name, internal=True, temporary=True)
        except gdb.error:
            super().__init__("*0x%x" % address, internal=True, temporary=True)
        self.thread = thread

    def stop(self) -> bool:
        # The step ends here, not at the next Python line.
        try:
            step = int(gdb.parse_and_eval("(unsigned long)&cppjit_debug_python_step"))
            gdb.selected_inferior().write_memory(step, b"\0\0\0\0")
        except gdb.error:
            pass
        return True


class _EnterJitBreak(gdb.Breakpoint):
    """Finds the C++ functions that a JIT call runs, during a step into."""

    def __init__(self) -> None:
        super().__init__(ENTER_JIT, internal=True)
        self.silent = True

    def stop(self) -> bool:
        thread = gdb.selected_thread()
        if thread is None or thread.num not in _entering:
            return False
        _entering.discard(thread.num)
        try:
            frame = gdb.newest_frame()
            architecture = frame.architecture()
            register = _ARGUMENT.get(architecture.name())
            if register is None:
                return False
            # Cpp::JitCall starts with the union of its wrapper function pointers.
            wrapper = _u64(int(frame.read_register(register)))
            for name, address in _called_functions(wrapper, architecture):
                _entries.append(_EntryBreak(name, address, thread.num))
        except (gdb.error, RuntimeError):
            pass
        return False


def _arm(objfile: gdb.Objfile) -> None:
    inferior = gdb.selected_inferior()
    if inferior.num in _breakpoints or not objfile.filename.endswith("libcppjit.so"):
        return
    _breakpoints[inferior.num] = (_PythonBreak(), _EnterJitBreak())


def _on_new_objfile(event: gdb.NewObjFileEvent) -> None:
    _arm(event.new_objfile)


def _set_int(symbol: str, value: int | str) -> bool:
    """Writes VALUE to the libcppjit variable SYMBOL; False if it is not loaded."""
    try:
        gdb.execute(
            "set var *(%s)&%s = %s" % (_TYPES[symbol], symbol, value), to_string=True
        )
    except gdb.error:
        return False
    return True


_TYPES = {
    "cppjit_debug_python_generation": "int*",
    "cppjit_debug_python_step": "int*",
    "cppjit_debug_python_step_thread": "unsigned long*",
}


def _on_stop(event: gdb.StopEvent) -> None:
    # cppjit.debugger reads breakpoints again when the generation changes.
    _set_int(
        "cppjit_debug_python_generation", "*(int*)&cppjit_debug_python_generation + 1"
    )
    _entering.clear()
    while _entries:
        entry = _entries.pop()
        if entry.is_valid():
            entry.delete()


# "return" goes on from C++ code to the Python frame that called it.
STEP_MODES = {"into": 1, "over": 2, "out": 3, "return": 4}


def request_step(mode: str) -> None:
    """Make the selected thread stop at its next Python line (MODE: into, over, out)."""
    thread = gdb.selected_thread()
    if thread is None:
        raise gdb.GdbError("No thread.")
    if not (
        _set_int("cppjit_debug_python_step_thread", thread.ptid[1])
        and _set_int("cppjit_debug_python_step", STEP_MODES[mode])
    ):
        raise gdb.GdbError("The process has not loaded libcppjit with Python stepping.")
    if mode == "into":
        _entering.add(thread.num)


def _on_exited(event: gdb.ExitedEvent) -> None:
    for breakpoint in _breakpoints.pop(event.inferior.num, ()):
        if breakpoint.is_valid():
            breakpoint.delete()


def install() -> None:
    gdb.events.new_objfile.connect(_on_new_objfile)
    gdb.events.stop.connect(_on_stop)
    gdb.events.exited.connect(_on_exited)
    for objfile in gdb.objfiles():
        _arm(objfile)
