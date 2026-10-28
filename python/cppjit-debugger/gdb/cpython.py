"""Read CPython's thread and frame state from process memory.

CPython 3.13 and later keep a table of structure offsets (_Py_DebugOffsets)
at the start of _PyRuntime for out-of-process tools. With it, a debugger
finds the Python frames of each thread without CPython debug information
and without code that runs in the stopped process. The table layout is
fixed only within a minor version, so each supported version has an entry
in _LAYOUTS.

This module does not import gdb: a READ(address, size) -> bytes callback
gives it access to memory. It must run on the Python that gdb embeds.
"""

from __future__ import annotations

import struct
from typing import Callable, Iterable, Iterator, Sequence

COOKIE = b"xdebugpy"

_COMMON_TAIL_313 = [
    ("tuple_object", ["size", "ob_item", "ob_size"]),
    ("list_object", ["size", "ob_item", "ob_size"]),
]
_OBJECTS_TAIL = [
    ("dict_object", ["size", "ma_keys", "ma_values"]),
    ("float_object", ["size", "ob_fval"]),
    ("long_object", ["size", "lv_tag", "ob_digit"]),
    ("bytes_object", ["size", "ob_size", "ob_sval"]),
    ("unicode_object", ["size", "state", "length", "asciiobject_size"]),
]

# (minor version) -> field groups of _Py_DebugOffsets, in order; each field is a uint64.
_LAYOUTS = {
    13: [
        ("runtime_state", ["size", "finalizing", "interpreters_head"]),
        (
            "interpreter_state",
            [
                "size",
                "id",
                "next",
                "threads_head",
                "gc",
                "imports_modules",
                "sysdict",
                "builtins",
                "ceval_gil",
                "gil_runtime_state",
                "gil_runtime_state_enabled",
                "gil_runtime_state_locked",
                "gil_runtime_state_holder",
            ],
        ),
        (
            "thread_state",
            [
                "size",
                "prev",
                "next",
                "interp",
                "current_frame",
                "thread_id",
                "native_thread_id",
                "datastack_chunk",
                "status",
            ],
        ),
        (
            "interpreter_frame",
            ["size", "previous", "executable", "instr_ptr", "localsplus", "owner"],
        ),
        (
            "code_object",
            [
                "size",
                "filename",
                "name",
                "qualname",
                "linetable",
                "firstlineno",
                "argcount",
                "localsplusnames",
                "localspluskinds",
                "co_code_adaptive",
            ],
        ),
        ("pyobject", ["size", "ob_type"]),
        ("type_object", ["size", "tp_name", "tp_repr", "tp_flags"]),
    ]
    + _COMMON_TAIL_313
    + _OBJECTS_TAIL,
    14: [
        ("runtime_state", ["size", "finalizing", "interpreters_head"]),
        (
            "interpreter_state",
            [
                "size",
                "id",
                "next",
                "threads_head",
                "threads_main",
                "gc",
                "imports_modules",
                "sysdict",
                "builtins",
                "ceval_gil",
                "gil_runtime_state",
                "gil_runtime_state_enabled",
                "gil_runtime_state_locked",
                "gil_runtime_state_holder",
                "code_object_generation",
                "tlbc_generation",
            ],
        ),
        (
            "thread_state",
            [
                "size",
                "prev",
                "next",
                "interp",
                "current_frame",
                "thread_id",
                "native_thread_id",
                "datastack_chunk",
                "status",
            ],
        ),
        (
            "interpreter_frame",
            [
                "size",
                "previous",
                "executable",
                "instr_ptr",
                "localsplus",
                "owner",
                "stackpointer",
                "tlbc_index",
            ],
        ),
        (
            "code_object",
            [
                "size",
                "filename",
                "name",
                "qualname",
                "linetable",
                "firstlineno",
                "argcount",
                "localsplusnames",
                "localspluskinds",
                "co_code_adaptive",
                "co_tlbc",
            ],
        ),
        ("pyobject", ["size", "ob_type"]),
        ("type_object", ["size", "tp_name", "tp_repr", "tp_flags"]),
    ]
    + _COMMON_TAIL_313
    + [("set_object", ["size", "used", "table", "mask"])]
    + _OBJECTS_TAIL,
}

# Owner of the entry frame that each C-level call of the eval loop pushes: FRAME_OWNED_BY_CSTACK
# in 3.13, FRAME_OWNED_BY_INTERPRETER in 3.14. Higher owners are not Python frames either.
_ENTRY_OWNER = {13: 3, 14: 3}
# _PyStackRef tag bits on f_executable and the fast locals.
_STACKREF_TAG = {13: 0, 14: 3}
# f_globals and f_locals of _PyInterpreterFrame; the debug offsets do not give them.
_F_GLOBALS, _F_LOCALS = 24, 40
# co_localspluskinds bits (CO_FAST_*); the argument bits exist from 3.14.
_KIND_ARGS = 0x02 | 0x04 | 0x08
_KIND_HIDDEN = 0x10
_KIND_CELL = 0x40 | 0x80
# Py_TPFLAGS_INLINE_VALUES, Py_TPFLAGS_MANAGED_DICT; instances keep the managed dict pointer at -24.
_INLINE_VALUES, _MANAGED_DICT = 1 << 2, 1 << 4
_MANAGED_DICT_OFFSET = -24
# PyTypeObject.tp_basicsize; ht_cached_keys of PyHeapTypeObject after sizeof(PyTypeObject), the
# five method tables and ht_name, ht_slots, ht_qualname.
_TP_BASICSIZE = 32
_HT_CACHED_KEYS = 8 * (4 + 36 + 3 + 10 + 2) + 24
# PyTypeObject.tp_base and tp_dict, after tp_flags.
_TP_BASE_AFTER_FLAGS, _TP_DICT_AFTER_FLAGS = 88, 96
# cppjit's proxies of C++ objects (src/cpyrt): CPPInstance has fObject and fFlags after
# PyObject_HEAD; with kIsExtended, fObject points to an ExtendedData, which starts with the object
# address and has fSmartClass at 32. Each bound namespace is a module "cppjit.gbl.NAME".
_CPP_INSTANCE, _CPP_SCOPE = "cppjit.CPPInstance", "cppjit.CPPScope"
_CPP_MODULE = "cppjit.gbl"
_CPP_IS_EXTENDED, _CPP_IS_REFERENCE, _CPP_IS_SMART = 0x0004, 0x0010, 0x0040
_CPP_SMART_CLASS = 32
_MAX_SCOPES = 4096
# Py_TPFLAGS_*_SUBCLASS bits.
_LONG, _LIST, _TUPLE, _BYTES, _UNICODE, _DICT, _, _TYPE = (
    1 << n for n in range(24, 32)
)

_MAX_FRAMES = 4096
_MAX_STRING = 4096
_MAX_ITEMS = 1000
_MAX_DIGITS = 100
_PREVIEW = 80


class Unsupported(Exception):
    """The process has no CPython runtime that this module can read."""


class PyFrame:
    """One Python frame: the function's qualified name, its file and its current line. ADDRESS and
    CODE are the addresses of the _PyInterpreterFrame and of its code object."""

    def __init__(
        self, name: str, filename: str, line: int, address: int = 0, code: int = 0
    ) -> None:
        self.name = name
        self.filename = filename
        self.line = line
        self.address = address
        self.code = code

    def __repr__(self) -> str:
        return "PyFrame(%r, %r, %r)" % (self.name, self.filename, self.line)


def _varint(data: bytes, i: int) -> tuple[int, int]:
    b = data[i]
    i += 1
    value, shift = b & 63, 0
    while b & 64:
        b = data[i]
        i += 1
        shift += 6
        value |= (b & 63) << shift
    return value, i


def _svarint(data: bytes, i: int) -> tuple[int, int]:
    value, i = _varint(data, i)
    return (-(value >> 1) if value & 1 else value >> 1), i


def code_line(linetable: bytes, firstlineno: int, index: int) -> int | None:
    """The line of code unit INDEX in a co_linetable (CPython's Objects/locations.md), or None."""
    line, address, i = firstlineno, 0, 0
    while i < len(linetable):
        first = linetable[i]
        i += 1
        code, length = (first >> 3) & 15, (first & 7) + 1
        here: int | None = line
        if code == 15:
            here = None
        elif code == 14:
            delta, i = _svarint(linetable, i)
            line += delta
            here = line
            for _ in range(3):
                _, i = _varint(linetable, i)
        elif code == 13:
            delta, i = _svarint(linetable, i)
            line += delta
            here = line
        elif code >= 10:
            line += code - 10
            here = line
            i += 2
        else:
            i += 1
        if address <= index < address + length:
            return here
        address += length
    return None


class Runtime:
    """CPython's runtime state at RUNTIME, the address of _PyRuntime. CODE_TYPE is the address of
    PyCode_Type, or None to accept any object as a code object."""

    def __init__(
        self,
        read: Callable[[int, int], bytes],
        runtime: int,
        code_type: int | None = None,
    ) -> None:
        self._read = read
        self.address = runtime
        self._code_type = code_type
        if read(runtime, 8) != COOKIE:
            raise Unsupported("no _Py_DebugOffsets cookie at _PyRuntime")
        self.version = self._u64(runtime + 8)
        self.minor = (self.version >> 16) & 0xFF
        if (self.version >> 24) != 3 or self.minor not in _LAYOUTS:
            raise Unsupported("CPython %x is not supported" % self.version)
        self.free_threaded = bool(self._u64(runtime + 16))
        self.offsets: dict[str, int] = {}
        index = 2
        for group, fields in _LAYOUTS[self.minor]:
            for field in fields:
                index += 1
                self.offsets[group + "." + field] = self._u64(runtime + 8 * index)
        # The size of PyObject_HEAD: the fields of other objects come after it.
        self._head = self.offsets["pyobject.ob_type"] + 8

    def _u64(self, address: int) -> int:
        return struct.unpack("<Q", self._read(address, 8))[0]

    def _i64(self, address: int) -> int:
        return struct.unpack("<q", self._read(address, 8))[0]

    def _u32(self, address: int) -> int:
        return struct.unpack("<I", self._read(address, 4))[0]

    def _i32(self, address: int) -> int:
        return struct.unpack("<i", self._read(address, 4))[0]

    def _off(self, name: str) -> int:
        return self.offsets[name]

    def string(self, obj: int) -> str:
        """The text of the str object at OBJ."""
        state = self._u32(obj + self._off("unicode_object.state"))
        length = min(self._i64(obj + self._off("unicode_object.length")), _MAX_STRING)
        kind, compact, ascii = (state >> 2) & 7, (state >> 5) & 1, (state >> 6) & 1
        if not compact or length < 0:
            return "?"
        data = obj + self._off("unicode_object.asciiobject_size")
        if not ascii:
            # PyCompactUnicodeObject adds utf8_length and utf8 to PyASCIIObject.
            data += 16
        raw = self._read(data, length * kind)
        return raw.decode(
            {1: "latin-1", 2: "utf-16-le", 4: "utf-32-le"}.get(kind, "latin-1"),
            "replace",
        )

    def bytes(self, obj: int) -> bytes:
        size = min(self._i64(obj + self._off("bytes_object.ob_size")), 1 << 20)
        return self._read(obj + self._off("bytes_object.ob_sval"), max(size, 0))

    def _c_string(self, address: int, limit: int = 256) -> str:
        raw = self._read(address, limit)
        return (
            raw[: raw.find(b"\0")].decode("utf-8", "replace") if b"\0" in raw else "?"
        )

    def _type(self, obj: int) -> int:
        return self._u64(obj + self._off("pyobject.ob_type"))

    def type_name(self, obj: int) -> str:
        return self._c_string(
            self._u64(self._type(obj) + self._off("type_object.tp_name"))
        )

    def _flags(self, obj: int) -> int:
        return self._u64(self._type(obj) + self._off("type_object.tp_flags"))

    def _ref(self, address: int) -> int:
        return self._u64(address) & ~_STACKREF_TAG[self.minor]

    def _long(self, obj: int) -> int | None:
        tag = self._u64(obj + self._off("long_object.lv_tag"))
        count = tag >> 3
        if count > _MAX_DIGITS:
            return None
        digits = struct.unpack(
            "<%dI" % count,
            self._read(obj + self._off("long_object.ob_digit"), 4 * count),
        )
        value = sum(d << (30 * i) for i, d in enumerate(digits))
        return -value if tag & 3 == 2 else value

    def _sequence(self, obj: int) -> list[int]:
        flags = self._flags(obj)
        group = "tuple_object" if flags & _TUPLE else "list_object"
        size = min(max(self._i64(obj + self._off(group + ".ob_size")), 0), _MAX_ITEMS)
        items = obj + self._off(group + ".ob_item")
        if not flags & _TUPLE:
            items = self._u64(items)
        if not size:
            return []
        return list(struct.unpack("<%dQ" % size, self._read(items, 8 * size)))

    def _entries(
        self, keys: int, values: int, limit: int = _MAX_ITEMS
    ) -> list[tuple[int, int]]:
        # PyDictKeysObject: dk_log2_index_bytes at 9, dk_kind at 10, dk_nentries at 24, dk_indices at 32.
        index_bytes, kind = self._read(keys + 9, 2)
        count = min(self._i64(keys + 24), limit)
        entries = keys + 32 + (1 << index_bytes)
        order: Sequence[int] = range(max(count, 0))
        if values:
            # PyDictValues: capacity at 0, size at 1, values at 8, then the insertion order bytes.
            capacity, size = self._read(values, 2)
            order = self._read(values + 8 + 8 * capacity, min(size, limit))
        items: list[tuple[int, int]] = []
        for i in order:
            if kind == 0:
                # PyDictKeyEntry: me_hash, me_key, me_value.
                key, value = struct.unpack("<QQ", self._read(entries + 24 * i + 8, 16))
            else:
                key, value = struct.unpack("<QQ", self._read(entries + 16 * i, 16))
                if values:
                    # A split table keeps the values in PyDictValues.values, at 8.
                    value = self._u64(values + 8 + 8 * i)
            if key and value:
                items.append((key, value))
        return items

    def dict_items(self, obj: int, limit: int = _MAX_ITEMS) -> list[tuple[int, int]]:
        """The (key, value) object addresses of the dict at OBJ, in insertion order."""
        return self._entries(
            self._u64(obj + self._off("dict_object.ma_keys")),
            self._u64(obj + self._off("dict_object.ma_values")),
            limit,
        )

    def attributes(self, obj: int) -> list[tuple[str, int]] | None:
        """The (name, object address) of the instance attributes of OBJ, or None."""
        tp, flags = self._type(obj), self._flags(obj)
        if not flags & _MANAGED_DICT:
            return None
        namespace = self._u64(obj + _MANAGED_DICT_OFFSET)
        if namespace:
            items = self.dict_items(namespace)
        elif flags & _INLINE_VALUES:
            values = obj + self._i64(tp + _TP_BASICSIZE)
            if not self._read(values + 3, 1)[0]:  # PyDictValues.valid
                return None
            keys = self._u64(tp + self._off("type_object.size") + _HT_CACHED_KEYS)
            items = self._entries(keys, values)
        else:
            return None
        return [(self.string(k), v) for k, v in items if self._flags(k) & _UNICODE]

    def variables(
        self, frame: PyFrame
    ) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        """The arguments and the local variables of FRAME, a PyFrame: two lists of (name, object
        address). Module and class bodies give the names in their namespace dict as locals."""
        code = frame.code
        names = self._sequence(
            self._u64(code + self._off("code_object.localsplusnames"))
        )
        kinds = self.bytes(self._u64(code + self._off("code_object.localspluskinds")))
        base = frame.address + self._off("interpreter_frame.localsplus")
        argcount = self._i32(code + self._off("code_object.argcount"))
        arguments: list[tuple[str, int]] = []
        local: list[tuple[str, int]] = []
        for i, name in enumerate(names):
            kind = kinds[i] if i < len(kinds) else 0
            if kind & _KIND_HIDDEN:
                continue
            obj = self._ref(base + 8 * i)
            if obj and kind & _KIND_CELL and self.type_name(obj) == "cell":
                obj = self._u64(obj + self._head)  # PyCellObject.ob_ref
            if obj:
                (arguments if kind & _KIND_ARGS or i < argcount else local).append(
                    (self.string(name), obj)
                )
        if not names:
            namespace = self._u64(frame.address + _F_LOCALS) or self._u64(
                frame.address + _F_GLOBALS
            )
            if namespace and self._flags(namespace) & _DICT:
                for key, value in self.dict_items(namespace):
                    if self._flags(key) & _UNICODE:
                        text = self.string(key)
                        if not (text.startswith("__") and text.endswith("__")):
                            local.append((text, value))
        return arguments, local

    def _name_at(self, obj: int, offset: int) -> str | None:
        name = self._u64(obj + offset)
        return self.string(name) if name and self._flags(name) & _UNICODE else None

    def _is_subtype(self, tp: int, name: str) -> bool:
        base = self._off("type_object.tp_flags") + _TP_BASE_AFTER_FLAGS
        for _ in range(64):
            if not tp:
                return False
            if self._c_string(self._u64(tp + self._off("type_object.tp_name"))) == name:
                return True
            tp = self._u64(tp + base)
        return False

    def _is_cpp_scope(self, obj: int) -> int:
        return self._flags(obj) & _TYPE and self._is_subtype(
            self._type(obj), _CPP_SCOPE
        )

    def cpp_name(self, tp: int) -> str | None:
        """The qualified C++ name of the cppjit proxy class TP, or None."""
        interp = next(self.interpreters(), None)
        if not interp:
            return None
        modules = self._u64(interp + self._off("interpreter_state.imports_modules"))
        pending: list[tuple[list[str], int]] = []
        for key, scope in self.dict_items(modules, limit=1 << 20):
            name = self.string(key) if self._flags(key) & _UNICODE else ""
            if name == _CPP_MODULE or name.startswith(_CPP_MODULE + "."):
                path = (
                    name[len(_CPP_MODULE) + 1 :].split(".")
                    if name != _CPP_MODULE
                    else []
                )
                if all(p.isidentifier() for p in path):
                    pending.append((path, scope))
        seen: set[int] = set()
        while pending and len(seen) < _MAX_SCOPES:
            path, scope = pending.pop(0)
            if scope in seen or not self._is_cpp_scope(scope):
                continue
            seen.add(scope)
            namespace = self._u64(
                scope + self._off("type_object.tp_flags") + _TP_DICT_AFTER_FLAGS
            )
            if not namespace:
                continue
            for key, value in self.dict_items(namespace, limit=1 << 16):
                if not self._flags(key) & _UNICODE:
                    continue
                if value == tp:
                    name = self.string(key)
                    # Template instances have their qualified name as the key.
                    if path and name.startswith("::".join(path) + "::"):
                        return name
                    return "::".join(path + [name])
                pending.append((path + [self.string(key)], value))
        return None

    def cpp_object(
        self, obj: int
    ) -> tuple[int | None, str, tuple[int, str] | None] | None:
        """For a cppjit proxy at OBJ: (address, C++ type name, smart), where smart is the
        (address, C++ type name) of the smart pointer that holds the object, or None. None if
        OBJ is not a proxy. The address of an object in a smart pointer is None."""
        tp = self._type(obj)
        if not self._is_subtype(tp, _CPP_INSTANCE):
            return None
        flags = self._u32(obj + self._head + 8)
        address = self._u64(obj + self._head)
        if flags & _CPP_IS_EXTENDED and address:
            extended, address = address, self._u64(address)
            if flags & _CPP_IS_SMART:
                smart = self.cpp_name(self._u64(extended + _CPP_SMART_CLASS))
                name = self.cpp_name(tp)
                return (
                    (None, name, (address, smart))
                    if address and smart and name
                    else None
                )
        elif address and flags & _CPP_IS_REFERENCE:
            address = self._u64(address)
        name = self.cpp_name(tp) if address else None
        return (address, name, None) if name else None

    def summary(self, obj: int, depth: int = 0) -> str:
        """A short text for the object at OBJ, like its repr() for the common types."""
        name, flags = self.type_name(obj), self._flags(obj)
        if name == "NoneType":
            return "None"
        if name == "bool":
            return "True" if self._long(obj) else "False"
        if flags & _LONG:
            value = self._long(obj)
            return "<int with many digits>" if value is None else str(value)
        if name == "float":
            return repr(
                struct.unpack(
                    "<d", self._read(obj + self._off("float_object.ob_fval"), 8)
                )[0]
            )
        if flags & _UNICODE:
            return _clip(repr(self.string(obj)))
        if flags & _BYTES:
            return _clip(repr(self.bytes(obj)[:_MAX_STRING]))
        if flags & (_LIST | _TUPLE | _DICT):
            if depth:
                return (
                    "{...}" if flags & _DICT else "[...]" if flags & _LIST else "(...)"
                )
            if flags & _DICT:
                parts = (
                    "%s: %s" % (self.summary(k, 1), self.summary(v, 1))
                    for k, v in self.dict_items(obj)
                )
                return _join("{", parts, "}")
            items = self._sequence(obj)
            parts = (self.summary(item, 1) for item in items)
            if flags & _LIST:
                return _join("[", parts, "]")
            return _join("(", parts, ",)" if len(items) == 1 else ")")
        if name == "type":
            return "<class '%s'>" % self._c_string(
                self._u64(obj + self._off("type_object.tp_name"))
            )
        if name == "function":
            # PyFunctionObject: func_globals, func_builtins, func_name, func_qualname.
            return "<function %s>" % self._name_at(obj, self._head + 24)
        if name == "module":
            # PyModuleObject: md_dict, md_def, md_state, md_weaklist, md_name.
            return "<module '%s'>" % self._name_at(obj, self._head + 32)
        return "<%s object at 0x%x>" % (name, obj)

    def children(self, obj: int) -> list[tuple[str, int]] | None:
        """The items of a list, tuple or dict at OBJ, or the attributes of another object, as
        (name, object address); None if it has none to show."""
        flags = self._flags(obj)
        if flags & _DICT:
            return [(self.summary(k, 1), v) for k, v in self.dict_items(obj)]
        if flags & (_LIST | _TUPLE):
            return [(str(i), item) for i, item in enumerate(self._sequence(obj))]
        if self.type_name(obj) in ("type", "module", "function"):
            return None
        return self.attributes(obj) or None

    def interpreters(self) -> Iterator[int]:
        interp = self._u64(self.address + self._off("runtime_state.interpreters_head"))
        while interp:
            yield interp
            interp = self._u64(interp + self._off("interpreter_state.next"))

    def thread_states(self) -> list[tuple[int, int]]:
        """[(PyThreadState address, native thread id)] of every interpreter."""
        found: list[tuple[int, int]] = []
        for interp in self.interpreters():
            tstate = self._u64(interp + self._off("interpreter_state.threads_head"))
            while tstate and len(found) < _MAX_FRAMES:
                found.append(
                    (
                        tstate,
                        self._u64(tstate + self._off("thread_state.native_thread_id")),
                    )
                )
                tstate = self._u64(tstate + self._off("thread_state.next"))
        return found

    def thread_state(self, native_thread_id: int) -> int | None:
        for tstate, tid in self.thread_states():
            if tid == native_thread_id:
                return tstate
        return None

    def _frame(self, frame: int) -> PyFrame | None:
        executable = (
            self._u64(frame + self._off("interpreter_frame.executable"))
            & ~_STACKREF_TAG[self.minor]
        )
        if not executable:
            return None
        if (
            self._code_type is not None
            and self._u64(executable + self._off("pyobject.ob_type")) != self._code_type
        ):
            return None
        name = self.string(self._u64(executable + self._off("code_object.qualname")))
        filename = self.string(
            self._u64(executable + self._off("code_object.filename"))
        )
        firstlineno = self._i32(executable + self._off("code_object.firstlineno"))
        instr = self._u64(frame + self._off("interpreter_frame.instr_ptr"))
        index = (instr - (executable + self._off("code_object.co_code_adaptive"))) // 2
        line = None
        if 0 <= index < (1 << 24):
            table = self.bytes(
                self._u64(executable + self._off("code_object.linetable"))
            )
            line = code_line(table, firstlineno, index)
        return PyFrame(
            name,
            filename,
            line if line is not None else firstlineno,
            frame,
            executable,
        )

    def segments(self, tstate: int) -> list[list[PyFrame]]:
        """The Python frames of TSTATE, newest first, split into one list per C-level run of the eval
        loop: segment K belongs to the K-th newest _PyEval_EvalFrameDefault native frame."""
        segments: list[list[PyFrame]] = []
        current: list[PyFrame] = []
        frame = self._u64(tstate + self._off("thread_state.current_frame"))
        entry = _ENTRY_OWNER[self.minor]
        for _ in range(_MAX_FRAMES):
            if not frame:
                break
            owner = self._read(frame + self._off("interpreter_frame.owner"), 1)[0]
            if owner == entry:
                segments.append(current)
                current = []
            elif owner < entry:
                py = self._frame(frame)
                if py is not None:
                    current.append(py)
            frame = self._u64(frame + self._off("interpreter_frame.previous"))
        if current:
            segments.append(current)
        return segments

    def gil_holder(self) -> int | None:
        """The native thread id of the thread that holds the main interpreter's GIL, 0 if the GIL is
        free, or None for free-threaded builds."""
        if self.free_threaded:
            return None
        interp = None
        for interp in self.interpreters():
            pass
        if interp is None:
            return 0
        gil = self._u64(interp + self._off("interpreter_state.ceval_gil"))
        base = self._off("interpreter_state.gil_runtime_state")
        if not gil or not self._i32(
            gil + self._off("interpreter_state.gil_runtime_state_locked") - base
        ):
            return 0
        holder = self._u64(
            gil + self._off("interpreter_state.gil_runtime_state_holder") - base
        )
        if not holder:
            return 0
        return self._u64(holder + self._off("thread_state.native_thread_id"))


def _clip(text: str) -> str:
    return text if len(text) <= _PREVIEW else text[: _PREVIEW - 3] + "..."


def _join(start: str, parts: Iterable[str], end: str) -> str:
    text = start
    for i, part in enumerate(parts):
        if len(text) > _PREVIEW:
            return text + ", ..." + end[-1]
        text += (", " if i else "") + part
    return text + end
