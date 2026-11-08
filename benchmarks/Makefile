# the C++ side of the benchmarks builds into a shared library next to its
# sources (load_reflection_info resolves the header as a sibling of the
# loaded Dict library)
soext = .so
ifeq ($(OS),Windows_NT)
  soext = .dll
endif

dictnames = calls

dicts = $(addprefix cpp/,$(addsuffix Dict$(soext),$(dictnames)))

all : $(dicts)

# CPPFLAGS can point at the valgrind headers, for counting instructions
cppflags= -std=c++17 -O2 -fPIC $(CPPFLAGS)

PLATFORM := $(shell uname -s)
ifeq ($(PLATFORM),Darwin)
  cppflags+=-dynamiclib -single_module -undefined dynamic_lookup
endif

# a worker can load the library while another rebuilds it, so publish it whole
cpp/%Dict$(soext): cpp/%.cxx cpp/%.h cpp/%_api.h cpp/%_api_impl.h
	$(CXX) $(cppflags) -shared -o $@.$$$$.tmp $< && mv -f $@.$$$$.tmp $@

.PHONY: clean

clean:
	-rm -f $(dicts) cpp/*.tmp
