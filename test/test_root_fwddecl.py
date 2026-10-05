class TestROOTFWDDECL:
    def test01_bases_of_class_from_forward_declaration(self):
        """A class only forward declared by its dictionary keeps its bases"""

        import cppjit

        cppjit.load_reflection_info("libFwdDeclBases")

        Derived = cppjit.gbl.FwdDeclBases.Derived
        assert cppjit.gbl.FwdDeclBases.Base in Derived.__mro__
        assert Derived().f() == 42
