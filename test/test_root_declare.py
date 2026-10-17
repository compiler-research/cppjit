import os
import subprocess

from pytest import mark
from support import IS_WINDOWS


class TestROOTDECLARE:
    @mark.skipif(IS_WINDOWS, reason="builds a dictionary with rootcling")
    def test01_include_header_of_autoloaded_dictionary(self, tmp_path):
        """include a #pragma once header whose dictionary its rootmap autoloads"""

        import cppjit

        name = "pragma_once_dict"
        header, linkdef = name + ".h", name + "LinkDef.h"
        rootmap, lib = name + ".rootmap", "lib%s.so" % name
        (tmp_path / header).write_text(
            "#pragma once\n"
            "namespace %s { struct Thing { int value() const { return 42; } }; }\n"
            % name
        )
        (tmp_path / linkdef).write_text(
            "#ifdef __CLING__\n#pragma link C++ class %s::Thing+;\n#endif\n" % name
        )

        bindir = cppjit.gbl.TROOT.GetBinDir().Data()
        rootcling = os.path.join(bindir, "rootcling")
        root_config = os.path.join(bindir, "root-config")
        subprocess.check_call(
            [rootcling, "-f", "dict.cxx", "-rmf", rootmap, "-rml", lib]
            + ["-I" + str(tmp_path), header, linkdef],
            cwd=tmp_path,
        )
        cxx = subprocess.check_output([root_config, "--cxx"], text=True).split()
        flags = subprocess.check_output(
            [root_config, "--cflags", "--libs"], text=True
        ).split()
        subprocess.check_call(
            cxx
            + ["-shared", "-fPIC", "-o", lib, "dict.cxx", "-I" + str(tmp_path)]
            + flags,
            cwd=tmp_path,
        )

        cppjit.add_include_path(str(tmp_path))
        cppjit.add_library_path(str(tmp_path))
        cppjit.gbl.gInterpreter.LoadLibraryMap(str(tmp_path / rootmap))

        cppjit.include(header)

        assert cppjit.gbl.pragma_once_dict.Thing().value() == 42
