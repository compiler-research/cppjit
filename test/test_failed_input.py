import cppjit
import pytest

# llvm/llvm-project#218149 is in clang-repl from LLVM 23.1.3.
HAS_LLVM_218149 = (
    cppjit.evaluate(
        "__clang_major__ * 10000 + __clang_minor__ * 100 + __clang_patchlevel__"
    )
    >= 230103
)

CODEGEN = (
    "CodeGen state after an error crashes IncrementalAction::GenModule; "
    "upstream: llvm#226285, #234493, #204152, #223305"
)


class TestFAILED_INPUT:
    """A failed input must leave the interpreter as it was before that input.

    Each test is one notebook story: earlier cells succeed, one cell fails,
    then the fixed cell and the earlier cells' code must still work.
    Names are unique per test because the interpreter is shared.
    """

    # --- parse and Sema errors ----------------------------------------------

    def test01_syntax_error_keeps_earlier_cells(self):
        """A syntax error does not disturb earlier declarations"""

        import cppjit

        cppjit.cppdef("int fi01_answer() { return 42; }")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("int fi01_broken( { return 1; }")
        assert cppjit.gbl.fi01_answer() == 42

        cppjit.cppdef("int fi01_broken() { return 1; }")
        assert cppjit.gbl.fi01_broken() == 1

    def test02_failed_input_is_withdrawn_whole(self):
        """The valid part of a failed input is withdrawn with it"""

        import cppjit

        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            int fi02_good = 1;
            int fi02_bad = fi02_undeclared;""")

        cppjit.cppdef("""\
        int fi02_good = 2;
        int fi02_bad = 3;""")
        assert cppjit.gbl.fi02_good == 2
        assert cppjit.gbl.fi02_bad == 3

    def test03_failed_class_can_be_redeclared(self):
        """A class from a failed input can be declared again, differently"""

        import cppjit

        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            struct FI03 { int a; };
            int fi03_use() { return FI03{}.missing; }""")

        cppjit.cppdef("""\
        struct FI03 { int a = 7; int b = 8; };
        int fi03_use() { return FI03{}.b; }""")
        assert cppjit.gbl.fi03_use() == 8
        assert cppjit.gbl.FI03().a == 7

    def test04_bad_redefinition_keeps_original(self):
        """A rejected redefinition keeps the earlier definition usable"""

        import cppjit

        cppjit.cppdef("struct FI04 { int v = 4; };")
        assert cppjit.gbl.FI04().v == 4

        with pytest.raises(SyntaxError):
            cppjit.cppdef("struct FI04 { double w; };")

        assert cppjit.gbl.FI04().v == 4
        cppjit.cppdef("int fi04_read() { return FI04{}.v; }")
        assert cppjit.gbl.fi04_read() == 4

    def test05_python_proxy_survives_failure(self):
        """A class that Python already uses still works after a failed input"""

        import cppjit

        cppjit.cppdef("struct FI05 { int get() const { return 5; } };")
        obj = cppjit.gbl.FI05()
        assert obj.get() == 5

        with pytest.raises(SyntaxError):
            cppjit.cppdef("int fi05_bad() { return FI05{}.nope(); }")

        assert obj.get() == 5
        assert cppjit.gbl.FI05().get() == 5

    def test06_cppexec_failure_keeps_state(self):
        """A failed statement does not disturb earlier globals"""

        import cppjit

        cppjit.cppdef("int fi06_counter = 0;")
        cppjit.cppexec("fi06_counter += 1")
        with pytest.raises(SyntaxError):
            cppjit.cppexec("fi06_counter += fi06_undeclared")
        cppjit.cppexec("fi06_counter += 1")
        assert cppjit.gbl.fi06_counter == 2

    def test07_many_failures_in_a_row(self):
        """Repeated failures do not build up state"""

        import cppjit

        cppjit.cppdef("int fi07_base() { return 7; }")
        for _ in range(25):
            with pytest.raises(SyntaxError):
                cppjit.cppdef("int fi07_retry() { return fi07_nope; }")
        cppjit.cppdef("int fi07_retry() { return fi07_base(); }")
        assert cppjit.gbl.fi07_retry() == 7

    def test08_failed_input_declares_special_member_of_earlier_class(self):
        """A failed input that used an earlier class's copy constructor"""

        import cppjit

        cppjit.cppdef("struct FI08 { int v = 8; };")
        with pytest.raises(SyntaxError):
            cppjit.cppdef(
                "int fi08_bad() { FI08 a; FI08 b = a; return b.v + fi08_nope; }"
            )
        cppjit.cppdef("int fi08_ok() { FI08 a; FI08 b = a; return b.v; }")
        assert cppjit.gbl.fi08_ok() == 8

    # --- templates first used by a failed input -----------------------------

    def test09_function_template(self):
        """A function template that a failed input instantiated"""

        import cppjit

        cppjit.cppdef("template <class T> T fi09_twice(T t) { return 2 * t; }")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            int fi09_y = fi09_twice(3);
            int fi09_z = fi09_undeclared;""")

        cppjit.cppdef("int fi09_again() { return fi09_twice(3); }")
        assert cppjit.gbl.fi09_again() == 6

    def test10_member_of_class_template(self):
        """A member function of a class template, first used by a failed input"""

        import cppjit

        cppjit.cppdef("""\
        template <class T> struct FI10 { T get() const { return T(10); } };""")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            int fi10_a = FI10<int>{}.get();
            int fi10_b = fi10_undeclared;""")

        cppjit.cppdef("int fi10_again() { return FI10<int>{}.get(); }")
        assert cppjit.gbl.fi10_again() == 10

    def test11_static_data_member_of_class_template(self):
        """A static data member of a class template, first used by a failed input"""

        import cppjit

        cppjit.cppdef("""\
        template <class T> struct FI11 { static T value; };
        template <class T> T FI11<T>::value = T(11);""")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            int fi11_a = FI11<int>::value;
            int fi11_b = fi11_undeclared;""")

        cppjit.cppdef("int fi11_again() { return FI11<int>::value; }")
        assert cppjit.gbl.fi11_again() == 11

    def test12_variable_template(self):
        """A variable template, first used by a failed input"""

        import cppjit

        cppjit.cppdef("template <class T> T fi12_v = T(12);")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            int fi12_a = fi12_v<int>;
            int fi12_b = fi12_undeclared;""")

        cppjit.cppdef("int fi12_again() { return fi12_v<int>; }")
        assert cppjit.gbl.fi12_again() == 12

    def test13_constexpr_function_template(self):
        """A constexpr function template, first used by a failed input"""

        import cppjit

        cppjit.cppdef(
            "template <class T> constexpr T fi13_twice(T t) { return 2 * t; }"
        )
        with pytest.raises(SyntaxError):
            cppjit.cppdef("int fi13_y = fi13_twice(3); int fi13_z = fi13_nope;")
        cppjit.cppdef("int fi13_again() { return fi13_twice(3); }")
        assert cppjit.gbl.fi13_again() == 6

    def test14_instantiation_with_withdrawn_type(self):
        """An instantiation with a type from a failed input does not stick"""

        import cppjit

        cppjit.cppdef("template <class T> int fi14_value(T t) { return t.v; }")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            struct FI14 {};
            int fi14_x = fi14_value(FI14{});""")

        cppjit.cppdef("""\
        struct FI14 { int v = 14; };
        int fi14_read() { return fi14_value(FI14{}); }""")
        assert cppjit.gbl.fi14_read() == 14

    def test15_python_template_instantiation_after_failure(self):
        """Python can instantiate a template that a failed input used"""

        import cppjit

        cppjit.cppdef("template <class T> T fi15_square(T t) { return t * t; }")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            double fi15_a = fi15_square(1.5);
            int fi15_b = fi15_undeclared;""")

        assert cppjit.gbl.fi15_square["double"](1.5) == 2.25

    def test16_deferred_template_of_earlier_cell(self):
        """An earlier cell's deferred instantiation survives a later failure"""

        import cppjit

        cppjit.cppdef("""\
        template <class T> T fi16_id(T t) { return t; }
        inline double fi16_use() { return fi16_id(1.5); }""")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("int fi16_bad() { return fi16_undeclared; }")

        assert cppjit.gbl.fi16_use() == 1.5

    # --- link and run-time failures ------------------------------------------

    def test17_missing_symbol_keeps_later_cells_working(self):
        """A cell that fails to link does not break later cells"""

        import cppjit

        with pytest.raises(SyntaxError):
            cppjit.cppexec("""\
            int fi17_undefined();
            int fi17_use = fi17_undefined()""")

        cppjit.cppdef("int fi17_later = 17;")
        assert cppjit.gbl.fi17_later == 17
        cppjit.cppexec("fi17_later += 1")
        assert cppjit.gbl.fi17_later == 18

    def test18_link_failure_then_retry_same_names(self):
        """A cell that failed to link can be fixed and run again"""

        import cppjit

        with pytest.raises(SyntaxError):
            cppjit.cppexec("""\
            int fi18_x = 1;
            int fi18_helper();
            int fi18_y = fi18_helper()""")

        cppjit.cppdef("""\
        int fi18_x = 2;
        int fi18_helper() { return 18; }
        int fi18_y = fi18_helper();""")
        assert cppjit.gbl.fi18_x == 2
        assert cppjit.gbl.fi18_y == 18

    def test19_python_call_to_undefined_function(self):
        """A Python call to a declared but undefined function fails cleanly"""

        import cppjit

        cppjit.cppdef("int fi19_nobody();")
        with pytest.raises(Exception):
            cppjit.gbl.fi19_nobody()

        cppjit.cppdef("int fi19_later() { return 19; }")
        assert cppjit.gbl.fi19_later() == 19

    def test20_evaluate_link_failure_keeps_later_cells(self):
        """A failed evaluate does not break later cells"""

        import cppjit

        cppjit.cppdef("int fi20_undefined();")
        try:
            cppjit.evaluate("fi20_undefined() + 1")
        except Exception:
            pass
        cppjit.cppdef("int fi20_later = 20;")
        cppjit.cppexec("fi20_later += 1")
        assert cppjit.gbl.fi20_later == 21

    def test21_initializer_throws(self):
        """A cell whose initializer throws is withdrawn"""

        import cppjit

        cppjit.cppdef(
            '#include <stdexcept>\nint fi21_thrower() { throw std::runtime_error("x"); }'
        )
        with pytest.raises(Exception):
            cppjit.cppdef("int fi21_v = fi21_thrower();")
        cppjit.cppdef("int fi21_v = 21;")
        assert cppjit.gbl.fi21_v == 21

    def test22_macro_from_failed_cell_is_gone(self):
        """A macro that a failed cell defined is not kept"""

        import cppjit

        with pytest.raises(SyntaxError):
            cppjit.cppdef("#define FI22_X 1\nint fi22_bad = fi22_nope;")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("int fi22 = FI22_X;")

    @pytest.mark.xfail(run=False, reason=CODEGEN)
    def test23_codegen_error_in_member_of_class_template(self):
        """A class template member bound to a withdrawn type does not stick"""

        import cppjit

        cppjit.cppdef("""\
        template <class T> struct FI23 { int get(T t) const { return t.v; } };""")
        with pytest.raises(SyntaxError):
            cppjit.cppdef("""\
            struct FI23Arg {};
            int fi23_x = FI23<FI23Arg>{}.get(FI23Arg{});""")

        cppjit.cppdef("""\
        struct FI23Arg { int v = 23; };
        int fi23_read() { return FI23<FI23Arg>{}.get(FI23Arg{}); }""")
        assert cppjit.gbl.fi23_read() == 23

    @pytest.mark.xfail(run=False, reason=CODEGEN)
    def test24_codegen_only_error_keeps_earlier_cells(self):
        """An error that only CodeGen finds does not drop earlier code"""

        import cppjit

        cppjit.cppdef("""\
        template <class T> T fi24_id(T t) { return t; }
        inline double fi24_use() { return fi24_id(2.5); }""")
        with pytest.raises(SyntaxError):
            cppjit.cppdef(
                'extern "C" void fi24_alias() __attribute__((alias("fi24_none")));'
            )

        assert cppjit.gbl.fi24_use() == 2.5
        cppjit.cppdef('extern "C" void fi24_alias() {}')
        cppjit.gbl.fi24_alias()

    @pytest.mark.xfail(
        strict=True,
        reason="ORC keeps a failed lookup's symbols in an error state, also "
        "after their module is removed; needs an ORC change",
    )
    def test25_lazy_link_failure_then_define_missing(self):
        """A function that failed to link works once the missing symbol exists"""

        import cppjit

        cppjit.cppdef("int fi25_missing(); int fi25_f() { return fi25_missing(); }")
        with pytest.raises(Exception):
            cppjit.gbl.fi25_f()
        cppjit.cppdef("int fi25_missing() { return 25; }")
        assert cppjit.gbl.fi25_f() == 25


class TestUNDO:
    """cppjit.undo() withdraws the last successful cppdef or cppexec."""

    def test01_redefine_variable(self):
        """Undo of a cell lets the same variable be declared again"""

        import cppjit

        cppjit.cppdef("int un01_value = 1;")
        cppjit.undo()
        cppjit.cppdef("int un01_value = 2;")
        assert cppjit.gbl.un01_value == 2

    def test02_name_gone_from_unqualified_lookup(self):
        """An undone name is not found by unqualified lookup"""

        import cppjit

        cppjit.cppdef("int un02_gone = 1;")
        cppjit.undo()
        with pytest.raises(SyntaxError):
            cppjit.cppdef("int un02_read() { return un02_gone; }")

    def test03_redefine_function_python_called(self):
        """Undo of a function that Python called lets it be defined again"""

        import cppjit

        cppjit.cppdef("int un03_f() { return 1; }")
        assert cppjit.gbl.un03_f() == 1
        cppjit.undo()
        cppjit.cppdef("int un03_f() { return 2; }")
        assert cppjit.gbl.un03_f() == 2

    def test04_two_steps(self):
        """Two undos withdraw the last two cells"""

        import cppjit

        cppjit.cppdef("int un04_a = 1;")
        cppjit.cppdef("int un04_b = un04_a + 1;")
        assert cppjit.gbl.un04_b == 2
        cppjit.undo()
        cppjit.undo()
        cppjit.cppdef("double un04_a = 0.5; double un04_b = 1.5;")
        assert cppjit.gbl.un04_a == 0.5
        assert cppjit.gbl.un04_b == 1.5

    def test05_class_python_used(self):
        """Undo of a class that Python used lets it be redefined"""

        import cppjit

        cppjit.cppdef("struct UN05 { int get() const { return 1; } };")
        assert cppjit.gbl.UN05().get() == 1
        cppjit.undo()
        cppjit.cppdef("struct UN05 { int v = 2; int get() const { return v; } };")
        assert cppjit.gbl.UN05().get() == 2

    def test06_cell_that_instantiated_earlier_template(self):
        """Undo of a cell that instantiated an earlier template"""

        import cppjit

        cppjit.cppdef("template <class T> T un06_tw(T t) { return 2 * t; }")
        cppjit.cppdef("int un06_a() { return un06_tw(3); }")
        assert cppjit.gbl.un06_a() == 6
        cppjit.undo()
        cppjit.cppdef("int un06_b() { return un06_tw(4); }")
        assert cppjit.gbl.un06_b() == 8

    def test07_lazy_link_failure_then_redefine(self):
        """A function that fails to link on its first call can be redone"""

        import cppjit

        cppjit.cppdef("int un07_missing(); int un07_f() { return un07_missing(); }")
        with pytest.raises(Exception):
            cppjit.gbl.un07_f()
        cppjit.undo()
        cppjit.cppdef("int un07_f() { return 7; }")
        assert cppjit.gbl.un07_f() == 7

    def test08_new_namespace(self):
        """Undo in a namespace that the undone cell opened"""

        import cppjit

        cppjit.cppdef("namespace UN08 { int v = 1; }")
        assert cppjit.gbl.UN08.v == 1
        cppjit.undo()
        cppjit.cppdef("namespace UN08 { double v = 0.5; }")
        assert cppjit.gbl.UN08.v == 0.5

    def test09_reopened_namespace(self):
        """Undo in a namespace that an earlier cell opened"""

        import cppjit

        cppjit.cppdef("namespace UN09 { int keep = 1; }")
        assert cppjit.gbl.UN09.keep == 1
        cppjit.cppdef("namespace UN09 { int v = 1; }")
        assert cppjit.gbl.UN09.v == 1
        cppjit.undo()
        cppjit.cppdef("namespace UN09 { double v = 0.5; }")
        assert cppjit.gbl.UN09.v == 0.5
        assert cppjit.gbl.UN09.keep == 1

    def test10_reopened_nested_namespace(self):
        """Undo in a nested namespace that an earlier cell opened"""

        import cppjit

        cppjit.cppdef("namespace UN10 { namespace In { int keep = 1; } }")
        cppjit.cppdef("namespace UN10 { namespace In { int v = 1; } }")
        assert cppjit.gbl.UN10.In.v == 1
        cppjit.undo()
        cppjit.cppdef("namespace UN10 { namespace In { double v = 0.5; } }")
        assert cppjit.gbl.UN10.In.v == 0.5
        assert cppjit.gbl.UN10.In.keep == 1

    def test11_definition_of_earlier_function_declaration(self):
        """Undo of a definition keeps the earlier declaration"""

        import cppjit

        cppjit.cppdef("int un11_f();")
        cppjit.cppdef("int un11_f() { return 1; }")
        cppjit.undo()
        cppjit.cppdef("int un11_f() { return 2; }")
        assert cppjit.gbl.un11_f() == 2

    def test12_definition_of_earlier_variable_declaration(self):
        """Undo of a variable definition keeps the earlier declaration"""

        import cppjit

        cppjit.cppdef("extern int un12_x;")
        cppjit.cppdef("int un12_x = 1;")
        cppjit.undo()
        cppjit.cppdef("int un12_x = 2;")
        assert cppjit.gbl.un12_x == 2

    def test13_unscoped_enumerators(self):
        """Undone enumerators are gone from lookup"""

        import cppjit

        cppjit.cppdef("enum UN13 { UN13_A = 1 };")
        cppjit.undo()
        cppjit.cppdef("enum UN13b { UN13_A = 2 };")
        assert cppjit.gbl.UN13_A == 2

    def test14_include_guard(self, tmp_path):
        """A header with an include guard can be included again after undo"""

        import cppjit

        h = tmp_path / "un14.h"
        h.write_text(
            "#ifndef UN14_H\n#define UN14_H\nstruct UN14 { int v = 14; };\n#endif\n"
        )
        cppjit.cppdef('#include "%s"' % h)
        cppjit.undo()
        cppjit.cppdef('#include "%s"' % h)
        cppjit.cppdef("int un14_read() { return UN14{}.v; }")
        assert cppjit.gbl.un14_read() == 14

    def test15_pragma_once(self, tmp_path):
        """A #pragma once header can be included again after undo"""

        import cppjit

        h = tmp_path / "un15.h"
        h.write_text("#pragma once\nstruct UN15 { int v = 15; };\n")
        cppjit.cppdef('#include "%s"' % h)
        cppjit.undo()
        cppjit.cppdef('#include "%s"' % h)
        cppjit.cppdef("int un15_read() { return UN15{}.v; }")
        assert cppjit.gbl.un15_read() == 15

    def test16_macro_gone(self):
        """A macro that an undone cell defined is gone"""

        import cppjit

        cppjit.cppdef("#define UN16 1\nint un16_dummy = 0;")
        cppjit.undo()
        with pytest.raises(SyntaxError):
            cppjit.cppdef("int un16 = UN16;")

    def test17_macro_value_restored(self):
        """Undo restores the macro value of the cell before"""

        import cppjit

        cppjit.cppdef("#define UN17 1\nint un17_dummy = 0;")
        cppjit.cppdef("#undef UN17\n#define UN17 2\nint un17_dummy2 = 0;")
        cppjit.undo()
        cppjit.cppdef("int un17 = UN17;")
        assert cppjit.gbl.un17 == 1

    def test18_raw_cpp_undo_from_python(self):
        """Cpp.Undo called from Python does not withdraw its own call wrapper"""

        import cppjit

        cppjit.cppdef("int un18_value = 1;")
        assert cppjit.gbl.Cpp.Undo(1) == 0
        cppjit.cppdef("int un18_value = 2;")
        assert cppjit.gbl.un18_value == 2

    def test19_object_of_undone_class_raises(self):
        """A method call on an object of an undone class raises"""

        import cppjit

        cppjit.cppdef("struct UN19 { int get() const { return 19; } };")
        obj = cppjit.gbl.UN19()
        assert obj.get() == 19
        cppjit.undo()
        with pytest.raises(Exception):
            obj.get()

    def test20_nothing_to_undo(self):
        """undo() with no cell left raises"""

        import cppjit

        cppjit._cells.clear()
        with pytest.raises(RuntimeError):
            cppjit.undo()

    @pytest.mark.xfail(
        not HAS_LLVM_218149,
        strict=True,
        reason="a class's redeclarations share private definition data; "
        "fixed by llvm#218149 in LLVM 23.1.3",
    )
    def test21_definition_of_earlier_class_declaration(self):
        """Undo of a class definition keeps the earlier declaration"""

        import cppjit

        cppjit.cppdef("struct UN21;")
        cppjit.cppdef("struct UN21 { int v = 1; };")
        cppjit.undo()
        cppjit.cppdef("struct UN21 { int v = 2; };")
        assert cppjit.gbl.UN21().v == 2

    @pytest.mark.xfail(
        strict=True,
        reason="clang caches a file's contents for the session; upstream: llvm#182750",
    )
    def test22_header_changed_on_disk(self, tmp_path):
        """A header edited after undo is read again"""

        import cppjit

        h = tmp_path / "un22.h"
        h.write_text("#pragma once\ninline int un22_v() { return 1; }\n")
        cppjit.cppdef('#include "%s"' % h)
        cppjit.undo()
        h.write_text("#pragma once\ninline int un22_v() { return 2; }\n")
        cppjit.cppdef('#include "%s"' % h)
        assert cppjit.gbl.un22_v() == 2
