"""Benchmarks of calling C++ functions from Python, in instructions.

Every case is measured twice:

- test_first_call: the first call of a function, which also pays for
  cppjit's lazy setup (wrapper generation, converter lookup, template
  instantiation, overload resolution). It calls the function from the `cold`
  copy of the API, after calling it once from the `warmup` copy: that call
  absorbs the process-wide first-use costs (say, the first converter for a
  type), which would otherwise land on whichever case happens to run first.
- test_successive_call: a call of the `hot` copy's function after a first one.
"""

import ctypes
import gc
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cppjit
import pytest
from cppjit import gbl

HERE = os.path.dirname(os.path.abspath(__file__))

# build the C++ side on demand
subprocess.run(["make", "cpp/callsDict.so"], cwd=HERE, check=True)
cppjit.load_reflection_info(os.path.join(HERE, "cpp", "callsDict"))

# get and check of callgrind marker functions
_markers: ctypes.CDLL = ctypes.CDLL(os.path.join(HERE, "cpp", "callsDict.so"))
_markers.bench_dump.argtypes = [ctypes.c_char_p]
_toggle = _markers.bench_toggle_collect

if (
    os.environ.get("CPPJIT_BENCH_CALLGRIND") == "1"
    and _markers.bench_on_valgrind() != 1
):
    raise RuntimeError(
        "counting instructions needs callgrind.sh and a callsDict.so built with "
        "the valgrind headers (make CPPFLAGS=-I<valgrind include dir>)"
    )

Invoker = Callable[[Any, tuple[Any, ...]], Any]
Args = Callable[[], tuple[Any, ...]]


def _measure(name: str, invoke: Invoker, fn: Any, args: tuple[Any, ...]) -> Any:
    gc.collect()
    gc.disable()
    _toggle()
    result = invoke(fn, args)
    _toggle()
    gc.enable()
    _markers.bench_dump(name.encode())
    return result


def _noop(fn: Any, args: tuple[Any, ...]) -> None:
    pass


# The markers' own cost, which collect subtracts from every count. The empty
# measurement mirrors _measure, so that only the call itself remains.
_measure("baseline", _noop, None, ())

# keeping arguments stay alive:
# a callback that dies hands its wrapper to the next one
_keepalive: list[tuple[Any, ...]] = []

_UNCHECKED: Any = object()


@dataclass(frozen=True)
class Case:
    group: str
    func: str
    args: Args
    expect: Any = _UNCHECKED
    # explicit template arguments, as in func[tmpl](*args)
    tmpl: str | None = None
    name: str | None = None

    @property
    def id(self) -> str:
        return "%s/%s" % (self.group, self.name or self.func)

    def invoker(self) -> Invoker:
        if self.tmpl is None:
            return lambda fn, args: fn(*args)
        tmpl = self.tmpl
        return lambda fn, args: fn[tmpl](*args)


def primitive_cases() -> list[Case]:
    # tag: (result, value arguments, pointer arguments, reference arguments)
    # The value arguments also serve the const reference. The char types'
    # pointers are C strings, so they take a str; the other pointers and all
    # references take a ctypes object.
    primitives: dict[str, tuple[Any, Args, Args, Args]] = {
        "bool": (
            True,
            lambda: (True,),
            lambda: (ctypes.c_bool(True),),
            lambda: (ctypes.c_bool(True),),
        ),
        "char": ("a", lambda: ("a",), lambda: ("a",), lambda: (ctypes.c_char(b"a"),)),
        "schar": ("\x01", lambda: (1,), lambda: ("\x01",), lambda: (ctypes.c_byte(1),)),
        "uchar": (
            "\x01",
            lambda: (1,),
            lambda: (ctypes.c_ubyte(1),),
            lambda: (ctypes.c_ubyte(1),),
        ),
        "wchar": ("a", lambda: ("a",), lambda: ("a",), lambda: (ctypes.c_wchar("a"),)),
        "char16": (
            "a",
            lambda: ("a",),
            lambda: ("a",),
            lambda: (ctypes.c_uint16(ord("a")),),
        ),
        "char32": (
            "a",
            lambda: ("a",),
            lambda: ("a",),
            lambda: (ctypes.c_uint32(ord("a")),),
        ),
        "short": (
            1,
            lambda: (1,),
            lambda: (ctypes.c_short(1),),
            lambda: (ctypes.c_short(1),),
        ),
        "ushort": (
            1,
            lambda: (1,),
            lambda: (ctypes.c_ushort(1),),
            lambda: (ctypes.c_ushort(1),),
        ),
        "int": (
            1,
            lambda: (1,),
            lambda: (ctypes.c_int(1),),
            lambda: (ctypes.c_int(1),),
        ),
        "uint": (
            1,
            lambda: (1,),
            lambda: (ctypes.c_uint(1),),
            lambda: (ctypes.c_uint(1),),
        ),
        "long": (
            1,
            lambda: (1,),
            lambda: (ctypes.c_long(1),),
            lambda: (ctypes.c_long(1),),
        ),
        "ulong": (
            1,
            lambda: (1,),
            lambda: (ctypes.c_ulong(1),),
            lambda: (ctypes.c_ulong(1),),
        ),
        "llong": (
            1,
            lambda: (1,),
            lambda: (ctypes.c_longlong(1),),
            lambda: (ctypes.c_longlong(1),),
        ),
        "ullong": (
            1,
            lambda: (1,),
            lambda: (ctypes.c_ulonglong(1),),
            lambda: (ctypes.c_ulonglong(1),),
        ),
        "float": (
            1.0,
            lambda: (1.0,),
            lambda: (ctypes.c_float(1.0),),
            lambda: (ctypes.c_float(1.0),),
        ),
        "double": (
            1.0,
            lambda: (1.0,),
            lambda: (ctypes.c_double(1.0),),
            lambda: (ctypes.c_double(1.0),),
        ),
        "ldouble": (
            1.0,
            lambda: (1.0,),
            lambda: (ctypes.c_longdouble(1.0),),
            lambda: (ctypes.c_longdouble(1.0),),
        ),
    }
    # cppjit has no converter for const references to the wide char types
    no_cref = {"wchar", "char16", "char32"}

    cases: list[Case] = []
    for tag, (result, args, ptr_args, ref_args) in primitives.items():
        cases.append(Case("primitive", "pass_" + tag, args, result))
        cases.append(Case("primitive", "pass_ptr_" + tag, ptr_args, result))
        cases.append(Case("primitive", "pass_ref_" + tag, ref_args, result))
        if tag not in no_cref:
            cases.append(Case("primitive", "pass_cref_" + tag, args, result))
    return cases


def string_cases() -> list[Case]:
    return [
        Case("string", "pass_string", lambda: ("abc",), "abc"),
        Case("string", "pass_string_cref", lambda: ("abc",), "abc"),
        Case("string", "pass_string_view", lambda: ("abc",), "abc"),
        Case("string", "pass_cstring", lambda: ("abc",), "abc"),
    ]


def class_cases() -> list[Case]:
    return [
        Case("class", "pass_point", lambda: (gbl.Point(),)),
        Case("class", "pass_color", lambda: (gbl.Blue,), gbl.Blue),
        Case("class", "pass_shape", lambda: (gbl.Shape.Square,), gbl.Shape.Square),
        Case(
            "class",
            "pass_value_args",
            lambda: (gbl.Point(), gbl.Red, gbl.Shape.Circle),
            0,
        ),
        Case(
            "class",
            "pass_ref_args",
            lambda: (gbl.Point(), gbl.Widget(), gbl.Shape.Circle),
            0,
        ),
        Case("class", "pass_ptr_args", lambda: (gbl.Point(), gbl.Widget(), gbl.Red), 0),
        Case(
            "class",
            "pass_mixed_args",
            lambda: (
                gbl.Particle(),
                gbl.Widget(),
                gbl.Point(),
                gbl.Red,
                gbl.Shape.Circle,
            ),
            0,
        ),
    ]


def overload_cases() -> list[Case]:
    args: list[Args] = [
        lambda: (gbl.Point(), gbl.Red),
        lambda: (gbl.Widget(), gbl.Shape.Circle),
        lambda: (gbl.Particle(), gbl.Point(), gbl.Red),
        lambda: (gbl.Widget(), gbl.Particle(), gbl.Point()),
        lambda: (gbl.Red, gbl.Shape.Circle),
    ]
    return [
        Case("overload", "overloaded", a, i + 1, name="overloaded_%d" % (i + 1))
        for i, a in enumerate(args)
    ]


def template_cases() -> list[Case]:
    cases = [
        Case("template", "tmpl_deduce", lambda: (1,), 1, name="tmpl_deduce(int)"),
        Case("template", "tmpl_deduce", lambda: (1.0,), 1.0, name="tmpl_deduce(float)"),
        Case(
            "template", "tmpl_deduce", lambda: (True,), True, name="tmpl_deduce(bool)"
        ),
    ]
    explicit: list[tuple[str, Args, Any]] = [
        ("bool", lambda: (True,), True),
        ("char", lambda: ("a",), "a"),
        ("short", lambda: (1,), 1),
        ("unsigned int", lambda: (1,), 1),
        ("long", lambda: (1,), 1),
        ("unsigned long long", lambda: (1,), 1),
        ("float", lambda: (1.0,), 1.0),
        ("double", lambda: (1.0,), 1.0),
        ("long double", lambda: (1.0,), 1.0),
    ]
    for tmpl, args, result in explicit:
        cases.append(
            Case(
                "template",
                "tmpl_pass",
                args,
                result,
                tmpl=tmpl,
                name="tmpl_pass[%s]" % tmpl,
            )
        )
    return cases


def template_overload_cases() -> list[Case]:
    # (case name, arguments, overload)
    calls: list[tuple[str, Args, int]] = [
        ("tmpl_overloaded_1(Point)", lambda: (gbl.Point(),), 1),
        ("tmpl_overloaded_2(Point)", lambda: (gbl.Point(), gbl.Red), 2),
        ("tmpl_overloaded_1(Widget)", lambda: (gbl.Widget(),), 1),
        ("tmpl_overloaded_2(Widget)", lambda: (gbl.Widget(), gbl.Red), 2),
        ("tmpl_overloaded_1(Particle)", lambda: (gbl.Particle(),), 1),
        ("tmpl_overloaded_2(Particle)", lambda: (gbl.Particle(), gbl.Red), 2),
        (
            "tmpl_overloaded_3(Point,Widget)",
            lambda: (gbl.Point(), gbl.Widget(), gbl.Shape.Circle),
            3,
        ),
        (
            "tmpl_overloaded_3(Particle,Point)",
            lambda: (gbl.Particle(), gbl.Point(), gbl.Shape.Circle),
            3,
        ),
    ]
    return [
        Case("template_overload", "tmpl_overloaded", args, overload, name=name)
        for name, args, overload in calls
    ]


def callback_cases() -> list[Case]:
    # The args build a new Python callable per call, so that the first call
    # also pays for wrapping it; the hot benchmark reuses one callable.
    return [
        Case(
            "callback",
            "invoke",
            lambda: (lambda x: x, 1),
            1,
            name="invoke(int(*)(int))",
        ),
        Case(
            "callback",
            "invoke",
            lambda: (lambda x: x, 1.0),
            1.0,
            name="invoke(double(*)(double))",
        ),
        Case(
            "callback",
            "invoke",
            lambda: (lambda p: 3, gbl.Point()),
            3,
            name="invoke(int(*)(const Point&))",
        ),
        Case(
            "callback",
            "invoke",
            lambda: (lambda w, c: 4, gbl.Widget(), gbl.Red),
            4,
            name="invoke(std::function<int(Widget&,Color)>)",
        ),
        Case(
            "callback",
            "invoke",
            lambda: (lambda x, y: x, 5, 6),
            5,
            tmpl="int",
            name="invoke[int](T(*)(T,T))",
        ),
        Case(
            "callback",
            "invoke",
            lambda: (lambda x, y: x, 5.0, 6.0),
            5.0,
            tmpl="double",
            name="invoke[double](T(*)(T,T))",
        ),
    ]


def _all_cases() -> list[Case]:
    return (
        primitive_cases()
        + string_cases()
        + class_cases()
        + overload_cases()
        + template_cases()
        + template_overload_cases()
        + callback_cases()
    )


CASES = _all_cases()
cases = pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])


def _check(case: Case, result: Any) -> None:
    if case.expect is not _UNCHECKED:
        assert result == case.expect, case.id


def _call(case: Case, ns: Any) -> tuple[Any, tuple[Any, ...]]:
    fn, args = getattr(ns, case.func), case.args()
    _keepalive.append(args)
    return fn, args


@cases
def test_first_call(request: pytest.FixtureRequest, case: Case) -> None:
    invoke = case.invoker()
    _check(case, invoke(*_call(case, cppjit.gbl.warmup)))
    _check(case, _measure(request.node.name, invoke, *_call(case, cppjit.gbl.cold)))


@cases
def test_successive_call(request: pytest.FixtureRequest, case: Case) -> None:
    invoke = case.invoker()
    fn, args = _call(case, cppjit.gbl.hot)
    _check(case, invoke(fn, args))
    _check(case, _measure(request.node.name, invoke, fn, args))
