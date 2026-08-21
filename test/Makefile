# the C++ sides of the tests live under cpp/ and build into shared
# libraries next to their sources (load_reflection_info resolves the
# header as a sibling of the loaded Dict.so)
dictnames = advancedcpp \
            advancedcpp2 \
            conversions \
            cpp11features \
            crossinheritance \
            datatypes \
            doc_helper \
            example01 \
            fragile \
            memory_analysis \
            operators \
            overloads \
            pythonizables \
            std_streams \
            stltypes \
            templates

dicts = $(addprefix cpp/,$(addsuffix Dict.so,$(dictnames)))

all : $(dicts)

PYTHON ?= python3
cppflags= -std=c++17 -O3 -fPIC -I$(shell $(PYTHON) -c 'import sysconfig as sc; print(sc.get_config_var("INCLUDEPY"))') -Wno-register

PLATFORM := $(shell uname -s)
ifeq ($(PLATFORM),Darwin)
  cppflags+=-dynamiclib -single_module -undefined dynamic_lookup -Wno-delete-non-virtual-dtor
endif

cpp/%Dict.so: cpp/%.cxx
	$(CXX) $(cppflags) -shared -o $@ $^

# convenience: `make datatypesDict.so` builds cpp/datatypesDict.so
%Dict.so: cpp/%Dict.so ;

.PHONY: test clean

test:
	pytest test_*.py

clean:
	-rm -f $(dicts)
