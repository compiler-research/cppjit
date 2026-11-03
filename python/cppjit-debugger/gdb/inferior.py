"""Access to the debugged process: memory, CPython state, environment, files."""

from __future__ import annotations

import json
import os

import gdb

from . import cpython

_runtimes: dict[tuple[int, int, int], cpython.Runtime] = {}
_indexes: dict[str, tuple[int, dict[str, str]]] = {}


def read(address: int, size: int) -> bytes:
    if size <= 0:
        return b""
    return bytes(gdb.selected_inferior().read_memory(address, size))


def _address_of(expression: str) -> int | None:
    try:
        return int(gdb.parse_and_eval("(unsigned long)(%s)" % expression))
    except gdb.error:
        return None


def runtime() -> cpython.Runtime:
    """The cpython.Runtime of the selected inferior; raises cpython.Unsupported without one."""
    address = _address_of("&_PyRuntime")
    if not address:
        raise cpython.Unsupported("no _PyRuntime symbol")
    inferior = gdb.selected_inferior()
    key = (inferior.num, inferior.pid, address)
    if key not in _runtimes:
        try:
            _runtimes[key] = cpython.Runtime(read, address, _address_of("&PyCode_Type"))
        except gdb.MemoryError as exc:
            raise cpython.Unsupported(str(exc))
    return _runtimes[key]


def python_segments(
    thread: gdb.InferiorThread | None = None,
) -> list[list[cpython.PyFrame]]:
    """The Python frames of THREAD (default: the selected thread), split per eval-loop run."""
    thread = thread or gdb.selected_thread()
    if thread is None:
        return []
    rt = runtime()
    tstate = rt.thread_state(thread.ptid[1])
    return rt.segments(tstate) if tstate else []


def _c_string(address: int, limit: int = 65536) -> bytes:
    out = b""
    while len(out) < limit:
        chunk = read(address + len(out), 256)
        end = chunk.find(b"\0")
        if end >= 0:
            return out + chunk[:end]
        out += chunk
    return out


def _start_environment() -> dict[str, str]:
    pid = gdb.selected_inferior().pid
    try:
        with open("/proc/%d/environ" % pid, "rb") as f:
            entries = f.read().split(b"\0")
    except OSError:
        return {}
    env = {}
    for entry in entries:
        name, _, value = entry.decode("utf-8", "replace").partition("=")
        if name:
            env[name] = value
    return env


def environment() -> dict[str, str]:
    """The environment of the selected inferior: libc's environ, so changes the process made
    after its start count, and core files work. Variables of the start environment that environ
    does not have are added: environ can lack some of them."""
    env = _start_environment()
    pointer = _address_of("(char **) environ")
    if pointer:
        try:
            for i in range(4096):
                entry = int.from_bytes(read(pointer + 8 * i, 8), "little")
                if not entry:
                    break
                name, _, value = (
                    _c_string(entry).decode("utf-8", "replace").partition("=")
                )
                env[name] = value
            return env
        except gdb.MemoryError:
            pass
    return env or dict(os.environ)


def source_dir() -> str | None:
    """The directory that receives the JIT inputs, or None."""
    return environment().get("CPPINTEROP_JIT_SOURCE_DIR") or None


def python_file(filename: str) -> str:
    """A file with the source of FILENAME, a code object's file name."""
    if os.path.isfile(filename):
        return filename
    directory = source_dir()
    pid = gdb.selected_inferior().pid
    if not directory or not pid:
        return filename
    index = os.path.join(directory, "python-sources-%d.json" % pid)
    try:
        stamp = os.stat(index).st_mtime_ns
    except OSError:
        return filename
    if _indexes.get(index, (None,))[0] != stamp:
        try:
            with open(index) as f:
                _indexes[index] = (stamp, json.load(f))
        except (OSError, ValueError):
            return filename
    return _indexes[index][1].get(filename, filename)
