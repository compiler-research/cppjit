"""Source-level debugging of JIT-compiled C++ with gdb (experimental).

The gdb tests need a cppjit built with CPPJIT_ENABLE_DEBUGGER_SUPPORT; the
decoder tests read the gdb extension from the source tree.

Each gdb test runs a Python script that does cppdef and then calls the C++
function, under gdb in batch mode or under gdb's DAP server.
"""

import glob
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import textwrap
import threading

import pytest

GDB = shutil.which("gdb")
# Settings of the inferior that can break gdb, which has its own libraries and Python.
_INFERIOR_ONLY = ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH")

SCRIPT = '''\
import cppjit

cppjit.cppdef("""
int jit_scale(int value, int factor) {
  int product = value * factor;
  int result = product + 1;  // RESULT
  return result;
}
int jit_scale_twice(int value) { return jit_scale(jit_scale(value, 2), 3); }
namespace jit_ns { struct Point { int x = 1; double y = 2.5; }; }
""")
cppjit.cppdef("""
#include <memory>
std::shared_ptr<jit_ns::Point> jit_shared() { return std::make_shared<jit_ns::Point>(); }
std::unique_ptr<jit_ns::Point> jit_unique() { return std::make_unique<jit_ns::Point>(); }
""")


def compute(value):
    data = {"scale": [value, 2.5], "name": "jit"}  # DATA
    point = cppjit.gbl.jit_ns.Point()
    numbers = cppjit.gbl.std.vector["int"]([4, 5])
    shared, unique = cppjit.gbl.jit_shared(), cppjit.gbl.jit_unique()
    return cppjit.gbl.jit_scale_twice(data["scale"][0])  # CALL_SITE


print("result", compute(5))  # MAIN
print("done")  # AFTER
'''


def _line_of(text, marker):
    return next(i for i, line in enumerate(text.splitlines(), 1) if marker in line)


def _gdb_version():
    try:
        out = subprocess.run(
            [GDB, "--version"],
            capture_output=True,
            text=True,
            timeout=30,
            env=_gdb_env(),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.search(r"(\d+)\.(\d+)", out.splitlines()[0] if out else "")
    return (int(found.group(1)), int(found.group(2))) if found else None


def _ptrace_denied():
    try:
        with open("/proc/sys/kernel/yama/ptrace_scope") as f:
            if int(f.read()) >= 3:
                return "ptrace is disabled (kernel.yama.ptrace_scope=3)"
    except (OSError, ValueError):
        pass
    # Containers can deny ptrace through seccomp: try it.
    probe = subprocess.run(
        [GDB, "-nx", "-batch", "-ex", "run", "--args", "/bin/sh", "-c", "exit 0"],
        capture_output=True,
        text=True,
        timeout=120,
        env=_gdb_env(),
    )
    if "exited normally" not in probe.stdout:
        return (
            "gdb cannot run a process: %s"
            % (probe.stdout + probe.stderr).strip()[-200:]
        )
    return None


def _gdb_env():
    return {k: v for k, v in os.environ.items() if k not in _INFERIOR_ONLY}


def _skip_reason(min_version):
    if not sys.platform.startswith("linux"):
        return "gdb tests run on Linux only"
    if GDB is None:
        return "no gdb on PATH"
    version = _gdb_version()
    if version is None or version < min_version:
        return "needs gdb >= %d.%d, found %s" % (min_version + (version,))
    return _ptrace_denied()


# gdb 15 runs the program in the launch request, before configurationDone.
_DAP_GDB = (16, 0)


def _require_gdb(min_version=(12, 0)):
    reason = _skip_reason(min_version)
    if reason:
        pytest.skip(reason)


needs_debug_offsets = pytest.mark.skipif(
    sys.version_info < (3, 13),
    reason="mixed backtraces read CPython 3.13+ debug offsets",
)


def _package_dir():
    return importlib.util.find_spec("cppjit").submodule_search_locations[0]


def _debugger_dir():
    return os.path.join(_package_dir(), "debugger")


def _gdb_script():
    return os.path.join(_debugger_dir(), "gdb", "cppjit_gdb.py")


# The gdb extension in the source tree; the decoders need no build.
_SOURCE_GDB_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir,
    "python",
    "cppjit-debugger",
    "gdb",
)
# Wheel tests run a copy of test/ without the source tree.
needs_source_gdb_dir = pytest.mark.skipif(
    not os.path.isdir(_SOURCE_GDB_DIR), reason="no python/cppjit-debugger next to test/"
)


@pytest.fixture
def session(tmp_path):
    """A directory with the script, and the environment of a debug session."""
    if not os.path.isdir(_debugger_dir()):
        pytest.skip("cppjit is built without CPPJIT_ENABLE_DEBUGGER_SUPPORT")
    (tmp_path / "script.py").write_text(SCRIPT)
    env = dict(
        os.environ,
        CPPJIT_DEBUGGER_SUPPORT="1",
        CPPINTEROP_JIT_SOURCE_DIR=str(tmp_path / "jit"),
    )
    return tmp_path, env


def _run_gdb(cwd, env, commands, args=("script.py",), load="source " + _gdb_script()):
    cmd = [
        GDB,
        "-nx",
        "-batch",
        "-iex",
        "set debuginfod enabled off",
        "-iex",
        "set pagination off",
    ]
    for name in _INFERIOR_ONLY:
        if name in env:
            cmd += ["-iex", "set environment %s %s" % (name, env[name])]
    cmd += ["-iex", load, "-ex", "set breakpoint pending on"]
    for command in commands:
        cmd += ["-ex", command]
    cmd += ["-ex", "kill", "--args", sys.executable] + list(args)
    gdb_env = {k: v for k, v in env.items() if k not in _INFERIOR_ONLY}
    out = subprocess.run(
        cmd, cwd=str(cwd), env=gdb_env, capture_output=True, text=True, timeout=600
    )
    return out.stdout + out.stderr


def _jit_input(directory, text):
    """The JIT input file in DIRECTORY that contains TEXT."""
    for path in glob.glob(os.path.join(str(directory), "input_*.cpp")):
        with open(path) as f:
            if text in f.read():
                return path
    raise AssertionError("no JIT input with %r in %s" % (text, directory))


@needs_source_gdb_dir
def test_line_table_decoder():
    """cpython.code_line agrees with code.co_lines() for each code unit"""

    cpython = _load_cpython()

    def sample(a, b):
        total = 0
        for i in range(a):
            if i % 2:
                total += b * i
        return total

    codes = [
        sample.__code__,
        test_line_table_decoder.__code__,
        textwrap.dedent.__code__,
        subprocess.run.__code__,
    ]
    for code in codes:
        for start, end, line in code.co_lines():
            for offset in range(start, end, 2):
                found = cpython.code_line(
                    code.co_linetable, code.co_firstlineno, offset // 2
                )
                assert found == line, (code.co_name, offset)


def _load_cpython():
    spec = importlib.util.spec_from_file_location(
        "_cppjit_gdb_cpython", os.path.join(_SOURCE_GDB_DIR, "cpython.py")
    )
    cpython = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cpython)
    return cpython


class _Point:
    def __init__(self):
        self.x = 1
        self.label = "p"


@needs_debug_offsets
@needs_source_gdb_dir
@pytest.mark.skipif(not os.path.exists("/proc/self/mem"), reason="no /proc/self/mem")
def test_variable_decoder():
    """cpython.Runtime reads the variables of a live frame of this process like repr()"""

    import ctypes

    cpython = _load_cpython()
    with open("/proc/self/mem", "rb", buffering=0) as memory:

        def read(address, size):
            memory.seek(address)
            return memory.read(size)

        runtime = cpython.Runtime(
            read,
            ctypes.addressof(ctypes.c_char.in_dll(ctypes.pythonapi, "_PyRuntime")),
        )

        def sample(a, *rest, **extra):
            big = -12345678901234567890
            ratio = 2.5
            text = "h\u00e9llo"
            items = [1, "a", None, True, [2]]
            table = {"k": (1,), 2: b"x"}
            point = _Point()
            materialized = _Point()
            materialized.__dict__
            materialized.more = 3

            def inner():
                return a

            tstate = runtime.thread_state(threading.get_native_id())
            frame = next(
                f
                for segment in runtime.segments(tstate)
                for f in segment
                if f.name.endswith("sample")
            )
            # The frame must be live while it is read.
            arguments, local = runtime.variables(frame)
            found = dict(arguments + local)
            return (
                [name for name, _ in arguments],
                {name: runtime.summary(obj) for name, obj in found.items()},
                {name: runtime.children(obj) for name, obj in found.items()},
                (big, ratio, text, items, table, point, materialized, inner),
            )

        arguments, shown, children, _ = sample(7, 8, x=9)
        # 3.13 has only co_argcount; 3.14 marks *args and **kwargs as arguments too.
        assert arguments == (
            ["a", "rest", "extra"] if sys.version_info >= (3, 14) else ["a"]
        )
        assert shown["a"] == "7"
        assert shown["rest"] == "(8,)" and shown["extra"] == "{'x': 9}"
        assert shown["big"] == "-12345678901234567890" and shown["ratio"] == "2.5"
        assert shown["text"] == repr("h\u00e9llo")
        assert shown["items"] == "[1, 'a', None, True, [...]]"
        assert shown["table"] == "{'k': (...), 2: b'x'}"
        assert shown["inner"].startswith("<function ") and "sample" in shown["inner"]
        assert shown["point"].startswith("<_Point object at 0x")
        assert [n for n, _ in children["point"]] == ["x", "label"]
        assert [n for n, _ in children["materialized"]] == ["x", "label", "more"]
        assert [n for n, _ in children["items"]] == ["0", "1", "2", "3", "4"]
        assert children["ratio"] is None


def test_debug_session_writes_sources(session):
    """CPPJIT_DEBUGGER_SUPPORT=1 writes the C++ inputs and in-memory Python to files"""

    tmp_path, env = session
    del env["CPPINTEROP_JIT_SOURCE_DIR"]
    env["TMPDIR"] = str(tmp_path)
    code = "import cppjit; cppjit.cppdef('int knob_probe() { return 1; }'); print(cppjit.debugger.source_dir())"
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert out.returncode == 0, out.stderr
    directory = out.stdout.strip().splitlines()[-1]
    assert directory.startswith(str(tmp_path))
    assert _jit_input(directory, "int knob_probe()")
    with open(glob.glob(os.path.join(directory, "python-sources-*.json"))[0]) as f:
        index = json.load(f)
    with open(index["<string>"]) as f:
        assert f.read() == code


def test_break_by_function(session):
    """break by name, show the source line, inspect locals, step"""

    _require_gdb()
    tmp_path, env = session
    out = _run_gdb(
        tmp_path,
        env,
        [
            "break jit_scale",
            "run",
            "info locals",
            "print value",
            "next",
            "next",
            "print product",
            "list",
        ],
    )
    assert re.search(
        r"Breakpoint 1, jit_scale \(value=5, factor=2\) at .*input_\w+\.cpp:3", out
    ), out
    assert "int product = value * factor;" in out
    assert re.search(r"^product = ", out, re.M)
    assert "$1 = 5" in out
    assert "return result;" in out
    assert "$2 = 10" in out


def test_break_by_file_line(session):
    """a pending file:line breakpoint binds in JIT code: input paths are the same on each run"""

    _require_gdb()
    tmp_path, env = session
    first = subprocess.run(
        [sys.executable, "script.py"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        timeout=600,
    )
    assert first.returncode == 0, first.stderr
    path = _jit_input(tmp_path / "jit", "int jit_scale(int value")
    with open(path) as f:
        line = _line_of(f.read(), "// RESULT")
    location = "%s:%d" % (os.path.basename(path), line)
    out = _run_gdb(
        tmp_path, env, ["break " + location, "run", "print product", "frame"]
    )
    assert "Breakpoint 1 (%s) pending." % location in out, out
    assert re.search(
        r"Breakpoint 1, jit_scale \(value=5, factor=2\) at .*%s" % re.escape(location),
        out,
    ), out
    assert "int result = product + 1;  // RESULT" in out
    assert "$1 = 10" in out


@needs_debug_offsets
def test_mixed_backtrace(session):
    """the backtrace puts the Python caller's file:line between the C++ frames"""

    _require_gdb()
    tmp_path, env = session
    out = _run_gdb(
        tmp_path,
        env,
        [
            "set cppjit internal-frames show",
            "break jit_scale",
            "run",
            "bt",
            "cppjit py-bt",
            "cppjit gil",
        ],
    )
    bt = out[out.index("#0 ") :]
    order = [
        r"#0 +jit_scale \(value=5, factor=2\) at \S+input_\w+\.cpp:3",
        r"in jit_scale_twice \(value=5\) at \S+input_\w+\.cpp:\d+",
        r"in \[py\] compute \(value=5\) at \S+script\.py:%d"
        % _line_of(SCRIPT, "CALL_SITE"),
        r"in \[py\] <module> \(\) at \S+script\.py:%d" % _line_of(SCRIPT, "MAIN"),
        r"Py_RunMain \(",
    ]
    position = 0
    for pattern in order:
        found = re.compile(pattern).search(bt, position)
        assert found, "%s not after offset %d in:\n%s" % (pattern, position, bt)
        position = found.end()
    assert 'return cppjit.gbl.jit_scale_twice(data["scale"][0])  # CALL_SITE' in out
    assert re.search(r"Thread 1 \(LWP \d+\) holds the GIL\.", out), out


@needs_debug_offsets
def test_python_source_from_memory(session):
    """the Python frames of `python -c` show a written copy of the code"""

    _require_gdb()
    tmp_path, env = session
    code = SCRIPT.replace("# CALL_SITE", "# IN_MEMORY")
    out = _run_gdb(
        tmp_path,
        env,
        ["break jit_scale", "run", "bt", "cppjit py-bt"],
        args=("-c", code),
    )
    found = re.search(
        r"in \[py\] compute \(value=5\) at (\S+py_\w+string\.py):%d"
        % _line_of(code, "IN_MEMORY"),
        out,
    )
    assert found, out
    assert 'return cppjit.gbl.jit_scale_twice(data["scale"][0])  # IN_MEMORY' in out


@needs_debug_offsets
def test_auto_load(session):
    """gdb loads the extension with libcppjit.so from a safe path"""

    _require_gdb()
    tmp_path, env = session
    out = _run_gdb(
        tmp_path,
        env,
        ["break jit_scale", "run", "cppjit py-bt"],
        load="add-auto-load-safe-path " + _package_dir(),
    )
    assert "Traceback (most recent call last):" in out, out
    assert 'return cppjit.gbl.jit_scale_twice(data["scale"][0])  # CALL_SITE' in out


NODE = shutil.which("node")
# A stop that does not come fails the test, not hangs it.
DAP_TIMEOUT = 300
DAP_PROXY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir,
    "examples",
    "vscode-gdb",
    "extension",
    "dap-proxy.js",
)


class _Dap:
    """A minimal client of gdb's DAP server over stdio."""

    def __init__(self, cwd, transcript, prefix=()):
        self._proc = subprocess.Popen(
            list(prefix)
            + [
                GDB,
                "-nx",
                "-i",
                "dap",
                "-iex",
                "set debuginfod enabled off",
                "-iex",
                "source " + _gdb_script(),
            ],
            cwd=str(cwd),
            env=_gdb_env(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._seq = 0
        self._pending = []
        self.transcript = transcript
        self._messages = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        while True:
            length = None
            while True:
                header = self._proc.stdout.readline()
                if not header:
                    self._messages.put(None)
                    return
                header = header.decode().strip()
                if not header:
                    break
                if header.lower().startswith("content-length:"):
                    length = int(header.split(":", 1)[1])
            self._messages.put(json.loads(self._proc.stdout.read(length)))

    def _read(self):
        try:
            message = self._messages.get(timeout=DAP_TIMEOUT)
        except queue.Empty:
            raise TimeoutError("no DAP message in %d s" % DAP_TIMEOUT) from None
        if message is None:
            raise EOFError("gdb closed its DAP stream")
        self.transcript.append(("<-", message))
        return message

    def send(self, command, **arguments):
        self._seq += 1
        message = {
            "seq": self._seq,
            "type": "request",
            "command": command,
            "arguments": arguments,
        }
        self.transcript.append(("->", message))
        data = json.dumps(message).encode()
        self._proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(data) + data)
        self._proc.stdin.flush()
        return self._seq

    def _next(self, wanted):
        for i, message in enumerate(self._pending):
            if wanted(message):
                return self._pending.pop(i)
        while True:
            message = self._read()
            if wanted(message):
                return message
            self._pending.append(message)

    def response(self, seq):
        message = self._next(
            lambda m: m.get("type") == "response" and m.get("request_seq") == seq
        )
        assert message["success"], "%s failed: %s %s" % (
            message.get("command"),
            message.get("message"),
            message.get("body"),
        )
        return message.get("body", {})

    def request(self, command, **arguments):
        return self.response(self.send(command, **arguments))

    def event(self, name):
        return self._next(lambda m: m.get("type") == "event" and m.get("event") == name)

    def close(self):
        try:
            self._proc.stdin.close()
            self._proc.wait(timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            self._proc.kill()
            self._proc.wait()


@needs_debug_offsets
def test_dap_session(session):
    """the VS Code path: gdb's DAP server binds a breakpoint in a JIT source file and shows a mixed stack"""

    _require_gdb(_DAP_GDB)
    tmp_path, env = session
    first = subprocess.run(
        [sys.executable, "script.py"],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        timeout=600,
    )
    assert first.returncode == 0, first.stderr
    path = _jit_input(tmp_path / "jit", "int jit_scale(int value")
    with open(path) as f:
        line = _line_of(f.read(), "// RESULT")

    transcript = []
    dap = _Dap(tmp_path, transcript)
    try:
        dap.request(
            "initialize",
            clientID="pytest",
            adapterID="cppjit-gdb",
            linesStartAt1=True,
            columnsStartAt1=True,
        )
        launch = dap.send(
            "launch",
            program=sys.executable,
            args=["script.py"],
            cwd=str(tmp_path),
            env=env,
        )
        dap.event("initialized")
        breakpoints = dap.request(
            "setBreakpoints", source={"path": path}, breakpoints=[{"line": line}]
        )
        assert len(breakpoints["breakpoints"]) == 1
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        assert stopped["reason"] == "breakpoint", stopped
        frames = dap.request(
            "stackTrace", threadId=stopped["threadId"], startFrame=0, levels=40
        )["stackFrames"]
        top = frames[0]
        assert top["name"].startswith("jit_scale") and top["line"] == line, top
        assert os.path.samefile(top["source"]["path"], path), top
        callers = [f for f in frames if f["name"] == "[py] compute"]
        assert callers and callers[0]["line"] == _line_of(SCRIPT, "CALL_SITE"), frames
        assert os.path.samefile(
            callers[0]["source"]["path"], str(tmp_path / "script.py")
        )
        scopes = dap.request("scopes", frameId=top["id"])["scopes"]
        values = {}
        for scope in scopes:
            if scope["variablesReference"] and scope["name"] != "Registers":
                for variable in dap.request(
                    "variables", variablesReference=scope["variablesReference"]
                )["variables"]:
                    values[variable["name"]] = variable["value"]
        assert values.get("value") == "5" and values.get("product") == "10", values
        dap.request("disconnect", terminateDebuggee=True)
    finally:
        dap.close()
        target = os.environ.get("CPPJIT_TEST_DAP_TRANSCRIPT")
        if target:
            with open(target, "w") as f:
                for direction, message in transcript:
                    if (
                        message.get("command") == "launch"
                        and message["type"] == "request"
                    ):
                        # Keep the user's environment out of the file.
                        arguments = dict(
                            message["arguments"],
                            env={k: env[k] for k in env if k.startswith("CPP")},
                        )
                        message = dict(message, arguments=arguments)
                    f.write("%s %s\n" % (direction, json.dumps(message)))


@needs_debug_offsets
@pytest.mark.skipif(NODE is None, reason="no node on PATH")
def test_dap_python_breakpoint(session):
    """the example's DAP proxy stops at a Python line and shows it as the top frame"""

    _require_gdb(_DAP_GDB)
    tmp_path, env = session
    script = str(tmp_path / "script.py")
    line = _line_of(SCRIPT, "CALL_SITE")
    dap = _Dap(tmp_path, [], prefix=(NODE, DAP_PROXY))
    try:
        dap.request("initialize", clientID="pytest", adapterID="cppjit-gdb")
        launch = dap.send(
            "launch",
            program=sys.executable,
            args=["script.py"],
            cwd=str(tmp_path),
            env=env,
        )
        dap.event("initialized")
        answer = dap.request(
            "setBreakpoints", source={"path": script}, breakpoints=[{"line": line}]
        )
        assert answer["breakpoints"][0]["verified"], answer
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        frames = dap.request(
            "stackTrace", threadId=stopped["threadId"], startFrame=0, levels=40
        )["stackFrames"]
        top = frames[0]
        assert top["name"] == "[py] compute" and top["line"] == line, frames[:3]
        assert os.path.samefile(top["source"]["path"], script), top
        dap.request("continue", threadId=stopped["threadId"])
        assert dap.event("exited")["body"]["exitCode"] == 0
        dap.request("disconnect")
    finally:
        dap.close()


@needs_debug_offsets
@pytest.mark.skipif(NODE is None, reason="no node on PATH")
def test_dap_python_breakpoint_added_while_stopped(session):
    """a Python breakpoint set at a C++ stop is hit right after Continue"""

    _require_gdb(_DAP_GDB)
    tmp_path, env = session
    script = str(tmp_path / "script.py")
    dap = _Dap(tmp_path, [], prefix=(NODE, DAP_PROXY))
    try:
        dap.request("initialize", clientID="pytest", adapterID="cppjit-gdb")
        launch = dap.send(
            "launch",
            program=sys.executable,
            args=["script.py"],
            cwd=str(tmp_path),
            env=env,
        )
        dap.event("initialized")
        dap.request("setFunctionBreakpoints", breakpoints=[{"name": "jit_scale"}])
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        dap.request(
            "setBreakpoints",
            source={"path": script},
            breakpoints=[{"line": _line_of(SCRIPT, "AFTER")}],
        )
        dap.request("setFunctionBreakpoints", breakpoints=[])
        dap.request("continue", threadId=stopped["threadId"])
        stopped = dap.event("stopped")["body"]
        top = dap.request(
            "stackTrace", threadId=stopped["threadId"], startFrame=0, levels=1
        )["stackFrames"][0]
        assert top["name"] == "[py] <module>", top
        assert top["line"] == _line_of(SCRIPT, "AFTER"), top
        dap.request("disconnect", terminateDebuggee=True)
    finally:
        dap.close()


def _proxy_launch(tmp_path, env):
    """A proxy session that launched script.py; returns it and the launch request."""
    dap = _Dap(tmp_path, [], prefix=(NODE, DAP_PROXY))
    dap.request(
        "initialize",
        clientID="pytest",
        adapterID="cppjit-gdb",
        supportsVariableType=True,
    )
    launch = dap.send(
        "launch", program=sys.executable, args=["script.py"], cwd=str(tmp_path), env=env
    )
    dap.event("initialized")
    return dap, launch


def _top(dap, stopped):
    return dap.request(
        "stackTrace", threadId=stopped["threadId"], startFrame=0, levels=40
    )["stackFrames"]


@needs_debug_offsets
@pytest.mark.skipif(NODE is None, reason="no node on PATH")
def test_dap_python_step_over(session):
    """Step Over at a return goes back to the caller's line, in the middle of that line"""

    _require_gdb(_DAP_GDB)
    tmp_path, env = session
    dap, launch = _proxy_launch(tmp_path, env)
    try:
        dap.request(
            "setBreakpoints",
            source={"path": str(tmp_path / "script.py")},
            breakpoints=[{"line": _line_of(SCRIPT, "CALL_SITE")}],
        )
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        assert _top(dap, stopped)[0]["name"] == "[py] compute"
        dap.request("next", threadId=stopped["threadId"])
        stopped = dap.event("stopped")["body"]
        assert stopped["reason"] == "step", stopped
        top = _top(dap, stopped)[0]
        assert top["name"] == "[py] <module>", top
        assert top["line"] == _line_of(SCRIPT, "MAIN"), top
        dap.request("disconnect", terminateDebuggee=True)
    finally:
        dap.close()


@needs_debug_offsets
@pytest.mark.skipif(NODE is None, reason="no node on PATH")
def test_dap_python_step_out(session):
    """Step Over goes to the next line of the function; Step Out stops in the caller's line"""

    _require_gdb(_DAP_GDB)
    tmp_path, env = session
    dap, launch = _proxy_launch(tmp_path, env)
    try:
        dap.request(
            "setBreakpoints",
            source={"path": str(tmp_path / "script.py")},
            breakpoints=[{"line": _line_of(SCRIPT, "DATA")}],
        )
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        dap.request("next", threadId=stopped["threadId"])
        stopped = dap.event("stopped")["body"]
        top = _top(dap, stopped)[0]
        assert top["name"] == "[py] compute", top
        assert top["line"] == _line_of(SCRIPT, "DATA") + 1, top
        dap.request("stepOut", threadId=stopped["threadId"])
        stopped = dap.event("stopped")["body"]
        assert stopped["reason"] == "step", stopped
        top = _top(dap, stopped)[0]
        assert top["name"] == "[py] <module>", top
        assert top["line"] == _line_of(SCRIPT, "MAIN"), top
        dap.request("disconnect", terminateDebuggee=True)
    finally:
        dap.close()


@needs_debug_offsets
@pytest.mark.skipif(NODE is None, reason="no node on PATH")
def test_dap_step_out_of_jit_code(session):
    """Step Out of the outermost JIT function stops at the Python line that called it, not in glue code"""

    _require_gdb(_DAP_GDB)
    tmp_path, env = session
    dap, launch = _proxy_launch(tmp_path, env)
    try:
        dap.request(
            "setFunctionBreakpoints",
            breakpoints=[{"name": "jit_scale_twice"}],
        )
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        frames = _top(dap, stopped)
        assert frames[0]["name"].startswith("jit_scale_twice"), frames[0]
        assert [f["name"] for f in frames[1:3]] == ["[py] compute", "[py] <module>"], (
            frames
        )
        dap.request("stepOut", threadId=stopped["threadId"])
        stopped = dap.event("stopped")["body"]
        assert stopped["reason"] == "step", stopped
        top = _top(dap, stopped)[0]
        assert top["name"] == "[py] compute", top
        assert top["line"] == _line_of(SCRIPT, "CALL_SITE"), top
        dap.request("disconnect", terminateDebuggee=True)
    finally:
        dap.close()


@needs_debug_offsets
@pytest.mark.skipif(NODE is None, reason="no node on PATH")
def test_dap_python_step_into_cpp(session):
    """Step Into at a Python line that calls C++ stops in the C++ function"""

    _require_gdb(_DAP_GDB)
    tmp_path, env = session
    dap, launch = _proxy_launch(tmp_path, env)
    try:
        dap.request(
            "setBreakpoints",
            source={"path": str(tmp_path / "script.py")},
            breakpoints=[{"line": _line_of(SCRIPT, "CALL_SITE")}],
        )
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        dap.request("stepIn", threadId=stopped["threadId"])
        stopped = dap.event("stopped")["body"]
        assert stopped["reason"] == "step", stopped
        frames = _top(dap, stopped)
        assert frames[0]["name"].startswith("jit_scale_twice"), frames[0]
        assert frames[1]["name"] == "[py] compute", frames[1]
        dap.request("continue", threadId=stopped["threadId"])
        assert dap.event("exited")["body"]["exitCode"] == 0
        dap.request("disconnect")
    finally:
        dap.close()


@needs_debug_offsets
def test_internal_frames(session):
    """bt hides the cppjit and CPython frames unless internal-frames is show"""

    _require_gdb()
    tmp_path, env = session
    hidden = _run_gdb(tmp_path, env, ["break jit_scale", "run", "bt"])
    assert "[py] compute" in hidden, hidden
    assert "CPPMethod::Execute" not in hidden and "__jc_" not in hidden, hidden
    shown = _run_gdb(
        tmp_path,
        env,
        ["set cppjit internal-frames show", "break jit_scale", "run", "bt"],
    )
    assert "CPPMethod::Execute" in shown and "__jc_" in shown, shown


def test_up_skips_internal_frames(session):
    """cppjit up goes from one JIT frame to its JIT caller and no further"""

    _require_gdb()
    tmp_path, env = session
    out = _run_gdb(
        tmp_path,
        env,
        ["break jit_scale", "run", "cppjit up", "cppjit up", "cppjit down"],
    )
    assert re.search(r"#\d+ .*jit_scale_twice", out), out
    assert "No more frames outside cppjit internals." in out, out
    assert re.search(r"#0 .*jit_scale \(", out), out


def _variables(dap, reference):
    found = dap.request("variables", variablesReference=reference)["variables"]
    return {v["name"]: v for v in found}


def _python_scopes(dap, frame):
    scopes = dap.request("scopes", frameId=frame["id"])["scopes"]
    return {
        s["name"]: _variables(dap, s["variablesReference"])
        for s in scopes
        if s["name"] != "Registers"
    }


@needs_debug_offsets
@pytest.mark.skipif(NODE is None, reason="no node on PATH")
def test_dap_python_variables(session):
    """a Python frame shows its arguments and locals, expands containers and answers hovers"""

    _require_gdb(_DAP_GDB)
    tmp_path, env = session
    dap, launch = _proxy_launch(tmp_path, env)
    try:
        dap.request(
            "setBreakpoints",
            source={"path": str(tmp_path / "script.py")},
            breakpoints=[{"line": _line_of(SCRIPT, "CALL_SITE")}],
        )
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        top = _top(dap, stopped)[0]
        scopes = _python_scopes(dap, top)
        assert scopes["Arguments"]["value"]["value"] == "5", scopes
        data = scopes["Locals"]["data"]
        assert data["value"] == "{'scale': [...], 'name': 'jit'}", data
        assert "type" not in data, data
        items = _variables(dap, data["variablesReference"])
        assert items["'name'"]["value"] == "'jit'", items
        scale = _variables(dap, items["'scale'"]["variablesReference"])
        assert [scale["0"]["value"], scale["1"]["value"]] == ["5", "2.5"], scale
        hover = dap.request(
            "evaluate", expression="data", frameId=top["id"], context="hover"
        )
        assert hover["result"] == data["value"] and hover["variablesReference"], hover
        point = scopes["Locals"]["point"]
        fields = _variables(dap, point["variablesReference"])
        assert [fields["x"]["value"], fields["y"]["value"]] == ["1", "2.5"], fields
        assert "vector<int" in scopes["Locals"]["numbers"].get("type", ""), scopes
        module = _top(dap, stopped)[1]
        assert module["name"] == "[py] <module>", module
        assert _python_scopes(dap, module)["Locals"]["compute"]["value"] == (
            "<function compute>"
        )
        dap.request("disconnect", terminateDebuggee=True)
    finally:
        dap.close()


@needs_debug_offsets
def test_python_variables_at_cpp_stop(session):
    """at a C++ stop, bt full shows the variables of the Python callers"""

    _require_gdb()
    tmp_path, env = session
    out = _run_gdb(tmp_path, env, ["break jit_scale", "run", "bt full"])
    assert re.search(r"\[py\] compute \(value=5\)", out), out
    assert "data = {'scale': [...], 'name': 'jit'}" in out, out
    assert "compute = <function compute>" in out, out
    assert "point = {x = 1, y = 2.5}" in out, out
    assert "shared = {x = 1, y = 2.5}" in out, out
    assert "unique = {x = 1, y = 2.5}" in out, out
    assert re.search(r"numbers = .*(_M_start|length 2)", out), out


HEADER = """\
#pragma once
struct JitCounter {
  void add(int x) {
    int doubled = x * 2;
    total += doubled;  // ADD
  }
  // The constructor has code here, after ADD, before the JIT compiles add.
  int total = 0;
};
"""

HEADER_SCRIPT = """\
import os

import cppjit

cppjit.add_include_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "inc"))
cppjit.include("jit_counter.h")
counter = cppjit.gbl.JitCounter()
counter.add(4)
print("total", counter.total)
"""


def _header_session(session):
    tmp_path, env = session
    (tmp_path / "inc").mkdir()
    header = tmp_path / "inc" / "jit_counter.h"
    header.write_text(HEADER)
    (tmp_path / "header.py").write_text(HEADER_SCRIPT)
    return tmp_path, env, str(header)


@needs_debug_offsets
def test_break_in_included_header(session):
    """a FILE:LINE breakpoint in a header waits for the JIT to compile its function"""

    _require_gdb((13, 0))
    tmp_path, env, header = _header_session(session)
    line = _line_of(HEADER, "// ADD")
    out = _run_gdb(
        tmp_path,
        env,
        ["break jit_counter.h:%d" % line, "run", "bt 1", "print doubled", "next"],
        args=("header.py",),
    )
    assert re.search(
        r"JitCounter::add \(this=\S+, x=4\) at \S*jit_counter\.h:%d" % line, out
    ), out
    assert "JitCounter::JitCounter" not in out, out  # not moved to the constructor
    assert "$1 = 8" in out, out
    assert re.search(r"^%d\s+}" % (line + 1), out, re.M), out


@needs_debug_offsets
def test_dap_break_in_included_header(session):
    """gdb's DAP server stops at a header line and gives the header's path"""

    _require_gdb(_DAP_GDB)
    tmp_path, env, header = _header_session(session)
    line = _line_of(HEADER, "// ADD")
    dap = _Dap(tmp_path, [])
    try:
        dap.request("initialize", clientID="pytest", adapterID="cppjit-gdb")
        launch = dap.send(
            "launch",
            program=sys.executable,
            args=["header.py"],
            cwd=str(tmp_path),
            env=env,
        )
        dap.event("initialized")
        dap.request(
            "setBreakpoints", source={"path": header}, breakpoints=[{"line": line}]
        )
        dap.request("configurationDone")
        dap.response(launch)
        stopped = dap.event("stopped")["body"]
        top = _top(dap, stopped)[0]
        assert top["name"].startswith("JitCounter::add") and top["line"] == line, top
        assert os.path.samefile(top["source"]["path"], header), top
        dap.request("disconnect", terminateDebuggee=True)
    finally:
        dap.close()
