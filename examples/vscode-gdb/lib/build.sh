#!/bin/sh
# Builds libhistogram.so with debug information, as if on another machine:
# the source paths in it point to /build/histogram, which does not exist here.
# To see the source in gdb, run `directory lib` (from the demo directory),
# or `set substitute-path /build/histogram lib`.
set -e
cd "$(dirname "$0")"
${CXX:-g++} -std=c++20 -g -O0 -Wno-cpp -fPIC -shared \
    -fdebug-prefix-map="$PWD"=/build/histogram \
    histogram.cpp -o libhistogram.so
