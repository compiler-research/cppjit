"""Source-level debugging of JIT-compiled C++ with gdb (experimental).

cppjit ships this package as ``cppjit.debugger`` only when it is built with
``-DCPPJIT_ENABLE_DEBUGGER_SUPPORT=ON``. Set ``CPPJIT_DEBUGGER_SUPPORT=1``
before ``import cppjit`` to start a debug session:

- The interpreter compiles all C++ with ``-g -O0``.
- Each C++ input (``cppdef``, ``include``, ...) goes to a file in
  ``source_dir()``, so gdb shows the source and binds ``file:line``
  breakpoints. File names are hashes of the input, so they stay the same
  between runs. ``CPPINTEROP_JIT_SOURCE_DIR`` overrides the directory.
- Python source that exists only in memory (``python -c``, notebook cells)
  goes to files there too, so mixed backtraces can show it.
- Python and C stdout are line buffered, so output shows before each stop.

Load the gdb extension with ``source <gdb_script()>`` in gdb, or let gdb
auto-load it with ``add-auto-load-safe-path <cppjit package dir>``.

Python line breakpoints: if ``CPPJIT_PY_BREAKPOINTS`` names a JSON file
``{"<path>": [line, ...]}``, each of these lines calls the native function
``cppjit_debug_break_python`` before it runs, and the gdb extension stops
there. The process reads the file again when it changes. The debugger can
also ask for a step to the next Python line (``cppjit py-step`` in gdb).
This needs ``sys.monitoring`` (Python 3.12 or later).
"""

from __future__ import annotations

import hashlib
import json
import linecache
import os
import sys
import threading
import time
from types import CodeType, FrameType, ModuleType
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    import ctypes
    from _ctypes import CFuncPtr

__all__ = ["enabled", "source_dir", "gdb_script", "write_python_source"]

_PYTHON_INDEX = "python-sources-%d.json"
_BREAKPOINTS = "CPPJIT_PY_BREAKPOINTS"
_POLL_SECONDS = 0.2
_written: dict[str, tuple[str, str]] = {}


def enabled() -> bool:
    """Whether this process runs a debug session (``CPPJIT_DEBUGGER_SUPPORT``)."""
    return os.environ.get("CPPJIT_DEBUGGER_SUPPORT", "") not in ("", "0")


def source_dir() -> str | None:
    """The directory that receives the JIT inputs, or None."""
    return os.environ.get("CPPINTEROP_JIT_SOURCE_DIR") or None


def gdb_script() -> str:
    """The path of the gdb extension script."""
    return os.path.join(os.path.dirname(__file__), "gdb", "cppjit_gdb.py")


def _default_source_dir() -> str:
    # The same as setDefaultSourceDir in libcppjit, which sets it first in C.
    return os.path.join(
        os.environ.get("TMPDIR") or "/tmp", "cppjit-debug-%d" % os.getuid()
    )


def write_python_source(filename: str, source: str | bytes) -> str | None:
    """Write SOURCE, the Python code compiled as FILENAME, to the source dir
    if FILENAME is not a file. Return the path written, or None."""
    directory = source_dir()
    if not directory or not source or os.path.isfile(filename):
        return None
    if isinstance(source, bytes):
        source = source.decode("utf-8", "replace")
    digest = hashlib.sha256(source.encode()).hexdigest()[:16]
    if _written.get(filename, (None,))[0] == digest:
        return _written[filename][1]
    base = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in os.path.basename(filename)
    )
    path = os.path.join(
        directory, "py_%s_%s.py" % (digest, base.strip("_") or "snippet")
    )
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        with open(path, "w") as f:
            f.write(source)
        _written[filename] = (digest, path)
        # The gdb extension maps code object file names to files through this index.
        index = os.path.join(directory, _PYTHON_INDEX % os.getpid())
        with open(index + ".tmp", "w") as f:
            json.dump({name: entry[1] for name, entry in _written.items()}, f)
        os.replace(index + ".tmp", index)
    except OSError:
        return None
    return path


def _on_audit(event: str, args: tuple[Any, ...]) -> None:
    if event != "compile":
        return
    try:
        source, filename = args[0], args[1]
        if not isinstance(filename, str) or filename.startswith("<frozen"):
            return
        if not isinstance(source, (str, bytes)):
            # An AST, as IPython compiles cells; IPython puts the text in linecache.
            source = "".join(linecache.getlines(filename))
        write_python_source(filename, source)
    except Exception:
        # An exception here would fail the compile() call that raised the event.
        pass


# 4 steps into the next Python line, but first stops in the calling frame after a JIT call.
_STEP_INTO, _STEP_OVER, _STEP_OUT, _STEP_RETURN = 1, 2, 3, 4


def _library_dirs() -> tuple[str, ...]:
    import sysconfig

    paths = sysconfig.get_paths()
    dirs = {os.path.realpath(paths[k]) for k in ("stdlib", "platstdlib") if k in paths}
    # A directory of symlinks, as in a nix profile, has another real path than its files.
    dirs.add(os.path.dirname(os.path.realpath(os.__file__)))
    dirs.add(os.path.realpath(os.path.dirname(os.path.dirname(__file__))))
    return tuple(d + os.sep for d in dirs)


class _PythonBreakpoints:
    """Line breakpoints and line steps in Python code, for a native debugger."""

    def __init__(self, path: str, monitoring: ModuleType, native: _Native) -> None:
        self._path = path
        self._mon = monitoring
        self._native = native
        self._generation: int | None = None
        self._stamp: int | None = None
        self._lines: dict[str, frozenset[int]] = {}
        self._files: dict[str, str] = {}
        self._library = _library_dirs()
        self._tool: int = monitoring.DEBUGGER_ID
        self._reload_lock = threading.Lock()
        self._poller: int | None = None
        # The step mode that the events were restarted for, and the frame depth it began at.
        self._armed = 0
        self._step_depth = 0
        # The caller that a step stops in after a return: its code, and its depth.
        self._return_to: tuple[CodeType, int] | None = None

    def start(self) -> bool:
        try:
            self._mon.use_tool_id(self._tool, "cppjit")
        except ValueError:
            return False  # Another debugger, such as debugpy, has the tool slot.
        self.reload()
        self._native.on_load(self._on_leave_jit)
        events = self._mon.events
        self._mon.register_callback(self._tool, events.LINE, self._on_line)
        self._mon.register_callback(self._tool, events.PY_RETURN, self._on_return)
        self._mon.register_callback(
            self._tool, events.INSTRUCTION, self._on_instruction
        )
        self._mon.set_events(self._tool, self._mon.events.LINE)
        poller = threading.Thread(
            target=self._poll, name="cppjit-py-breakpoints", daemon=True
        )
        poller.start()
        self._poller = poller.ident
        return True

    def reload(self) -> bool:
        """Read the file if it changed; return True if it did."""
        # The poll thread and the line events both reload; a line must not
        # see the new stamp with the old lines.
        with self._reload_lock:
            return self._reload()

    def _reload(self) -> bool:
        try:
            stamp = os.stat(self._path).st_mtime_ns
        except OSError:
            stamp = None
        if stamp == self._stamp:
            return False
        self._stamp = stamp
        try:
            with open(self._path) as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        self._lines = {
            os.path.realpath(name): frozenset(lines) for name, lines in data.items()
        }
        return True

    def _poll(self) -> None:
        while True:
            time.sleep(_POLL_SECONDS)
            # A step that began in native code finds no Python code to arm it.
            stepping = self._native.step_mode() and not self._armed
            if self.reload() or stepping:
                # Lines that returned DISABLE get their events back.
                self._mon.restart_events()
                if stepping:
                    self._armed = self._native.step_mode()

    def _path_of(self, code: CodeType) -> str:
        name = code.co_filename
        path = self._files.get(name)
        if path is None:
            path = self._files[name] = os.path.realpath(name)
        return path

    def _depth(self, frame: FrameType | None) -> int:
        depth = 0
        while frame is not None:
            depth += 1
            frame = frame.f_back
        return depth

    def _step_stops(self, mode: int, path: str, frame: FrameType) -> bool:
        if path.startswith(self._library) or path.startswith("<"):
            return False
        if mode in (_STEP_INTO, _STEP_RETURN):
            return True
        depth = self._depth(frame)
        return (
            depth <= self._step_depth
            if mode == _STEP_OVER
            else depth < self._step_depth
        )

    def _stop(self, frame: FrameType) -> None:
        self._native.clear_step()
        self._armed = 0
        self._end_return_step()
        self._native.break_python()
        # The debugger may have asked for a step during the stop.
        mode = self._native.step_mode()
        if mode:
            self._step_depth = self._depth(frame)
            self._armed = mode
            if mode in (_STEP_OVER, _STEP_OUT):
                events = self._mon.events
                self._mon.set_events(self._tool, events.LINE | events.PY_RETURN)
            self._mon.restart_events()

    def _end_return_step(self) -> None:
        self._mon.set_events(self._tool, self._mon.events.LINE)
        if self._return_to is not None:
            self._mon.set_local_events(self._tool, self._return_to[0], 0)
            self._return_to = None

    def _stepping_here(self) -> int:
        return (
            self._native.step_mode()
            and self._native.step_thread() == threading.get_native_id()
        )

    def _on_return(self, code: CodeType, offset: int, value: object) -> None:
        # A return into the middle of a line has no line event: stop at the
        # caller's next instruction.
        try:
            if not self._stepping_here() or self._return_to is not None:
                return None
            frame = sys._getframe(1)
            if self._depth(frame) != self._step_depth or frame.f_back is None:
                return None
            caller = frame.f_back
            path = self._path_of(caller.f_code)
            if path.startswith(self._library) or path.startswith("<"):
                return None
            self._return_to = (caller.f_code, self._step_depth - 1)
            self._mon.set_local_events(
                self._tool, caller.f_code, self._mon.events.INSTRUCTION
            )
        except Exception:
            self._fail()
        return None

    def _on_leave_jit(self) -> None:
        # A step out of C++ code: stop in the Python frame that called it.
        try:
            if (
                self._native.step_mode() != _STEP_RETURN
                or not self._stepping_here()
                or self._return_to is not None
            ):
                return
            frame: FrameType | None = sys._getframe(1)
            while frame is not None:
                path = self._path_of(frame.f_code)
                if not (path.startswith(self._library) or path.startswith("<")):
                    break
                frame = frame.f_back
            if frame is None:
                return
            self._return_to = (frame.f_code, self._depth(frame))
            self._mon.set_local_events(
                self._tool, frame.f_code, self._mon.events.INSTRUCTION
            )
        except Exception:
            self._fail()

    def _on_instruction(self, code: CodeType, offset: int) -> None:
        try:
            target = self._return_to
            if target is None or code is not target[0] or not self._stepping_here():
                return None
            frame = sys._getframe(1)
            if self._depth(frame) == target[1]:
                self._stop(frame)
        except Exception:
            self._fail()
        return None

    def _on_line(self, code: CodeType, line: int) -> object:
        try:
            return self._line_event(code, line)
        except Exception:
            self._fail()
            return None

    def _fail(self) -> None:
        # An exception here would go to the user's code; stop watching instead.
        self._mon.set_events(self._tool, 0)
        import traceback

        print("cppjit.debugger: Python breakpoints are off after:", file=sys.stderr)
        traceback.print_exc()

    def _line_event(self, code: CodeType, line: int) -> object:
        if threading.get_ident() == self._poller:
            return self._mon.DISABLE
        generation = self._native.generation()
        if generation != self._generation:
            # The debugger stopped since the last check: take breakpoints set
            # in the stop. Another thread must not see the generation as
            # seen before the lines are read.
            with self._reload_lock:
                changed = self._reload()
                self._generation = generation
            if changed:
                self._mon.restart_events()
        path = self._path_of(code)
        frame = sys._getframe(2)
        mode = self._native.step_mode()
        if mode and self._native.step_thread() == threading.get_native_id():
            if line in self._lines.get(path, ()) or self._step_stops(mode, path, frame):
                self._stop(frame)
            return None  # Each line must report while the step runs.
        if line not in self._lines.get(path, ()):
            return self._mon.DISABLE
        self._stop(frame)
        return None


class _Native:
    """The debugger hooks in libcppjit, found once cppjit has loaded it."""

    _generation: ctypes.c_int
    _step: ctypes.c_int
    _step_thread: ctypes.c_ulong

    def __init__(self) -> None:
        self._lib: ctypes.CDLL | None = None
        self._on_leave: Callable[[], None] | None = None
        self._hook: CFuncPtr | None = None

    def on_load(self, on_leave: Callable[[], None]) -> None:
        """Make the library call ON_LEAVE after each JIT call during a step."""
        self._on_leave = on_leave

    def _loaded(self) -> ctypes.CDLL | None:
        if self._lib is None:
            # Until its import completes, the module has no spec; loading the
            # library first here would also come before cppjit's own preload.
            module = sys.modules.get("cppjit.libcppjit")
            origin = getattr(getattr(module, "__spec__", None), "origin", None)
            if not origin:
                return None
            import ctypes

            lib = ctypes.CDLL(origin)
            lib.cppjit_debug_break_python.restype = None
            self._generation = ctypes.c_int.in_dll(
                lib, "cppjit_debug_python_generation"
            )
            self._step = ctypes.c_int.in_dll(lib, "cppjit_debug_python_step")
            self._step_thread = ctypes.c_ulong.in_dll(
                lib, "cppjit_debug_python_step_thread"
            )
            if self._on_leave is not None:
                self._hook = ctypes.CFUNCTYPE(None)(self._on_leave)
                ctypes.c_void_p.in_dll(
                    lib, "cppjit_debug_python_return_hook"
                ).value = ctypes.cast(self._hook, ctypes.c_void_p).value
            self._lib = lib
        return self._lib

    def generation(self) -> int | None:
        return self._generation.value if self._loaded() else None

    def step_mode(self) -> int:
        return self._step.value if self._loaded() else 0

    def step_thread(self) -> int:
        return self._step_thread.value if self._loaded() else 0

    def clear_step(self) -> None:
        if self._loaded():
            self._step.value = 0

    def break_python(self) -> None:
        lib = self._loaded()
        if lib:
            lib.cppjit_debug_break_python()


def _start_python_breakpoints() -> _PythonBreakpoints | None:
    path = os.environ.get(_BREAKPOINTS)
    monitoring = getattr(sys, "monitoring", None)
    if not path or monitoring is None:
        return None
    breakpoints = _PythonBreakpoints(path, monitoring, _Native())
    return breakpoints if breakpoints.start() else None


def _flush_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, write_through=True)  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass  # Not a TextIOWrapper, for example a Jupyter stream.


def _configure() -> None:
    """Prepare the process for a debug session; libcppjit calls this when it loads."""
    if not enabled():
        return
    os.environ.setdefault("CPPINTEROP_JIT_SOURCE_DIR", _default_source_dir())
    argv = getattr(sys, "orig_argv", [])
    if "-c" in argv[:-1]:
        write_python_source("<string>", argv[argv.index("-c") + 1])
    sys.addaudithook(_on_audit)
    # Output must show at once when a debugger stops the process.
    _flush_output()
    _start_python_breakpoints()
