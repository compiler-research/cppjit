cmake_minimum_required(VERSION 3.20)
project(CppJIT LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(ExternalProject)
include(GNUInstallDirs)

# This option won't make a lot of sense since we only ship the shared library in site-packages
# Perhaps this should permanently be OFF and users can build their own CppInterOp if they want to run the tests?
option(CPPJIT_ENABLE_CPPINTEROP_TESTS "enable CppInterOp tests" OFF)
set(CPPINTEROP_GIT_REPOSITORY "https://github.com/compiler-research/CppInterOp.git" CACHE STRING "")
set(CPPINTEROP_GIT_TAG "8d624c621a4b95e36ff73ac708c85a768287478f" CACHE STRING "")
set(CPPINTEROP_SOURCE_DIR "" CACHE PATH
    "Override default CppInterOp built by ExternalProject_Add, with a path to local CppInterOp source")
# Providing CppInterOp_DIR selects external mode: cppjit consumes that
# CppInterOp via find_package instead of building and bundling one, baking
# its absolute paths into the wrapper. The search is keyed to the explicit
# variable rather than the default search paths: find_package succeeding
# here decides whether the wheel bundles its interpreter at all, and that
# must not silently depend on the build environment (e.g. a conda env that
# happens to carry CppInterOp). Like LLVM_DIR below, an explicit dir is
# authoritative: a failed find_package resets CppInterOp_DIR to -NOTFOUND,
# so keep the requested value for the message and fail instead of falling
# back to the bundled build.
if(CppInterOp_DIR)
    set(_cppinterop_dir_arg "${CppInterOp_DIR}")
    find_package(CppInterOp CONFIG PATHS "${CppInterOp_DIR}" NO_DEFAULT_PATH)
    if(NOT CppInterOp_FOUND)
        message(FATAL_ERROR
            "No CppInterOpConfig.cmake under CppInterOp_DIR (${_cppinterop_dir_arg}); "
            "expected <install prefix>/lib/cmake/CppInterOp")
    endif()
endif()

# The full Development component requires libpython, which manylinux
# images do not ship and extension modules do not need.
set(Python_FIND_VIRTUALENV ONLY)
find_package(Python COMPONENTS Interpreter Development.Module)
if(NOT Python_FOUND)
    set(Python_FIND_VIRTUALENV STANDARD)
    find_package(Python COMPONENTS Interpreter Development.Module)
endif()
if(NOT Python_Development.Module_FOUND)
    message(FATAL_ERROR "Python development headers not found")
endif()

if(CppInterOp_FOUND)
    # The package config records the absolute library/include locations and
    # the LLVM version the library embeds, so no LLVM is needed to build the
    # wrapper itself; version compatibility was already enforced when that
    # CppInterOp was built.
    # The config computes CPPINTEROP_INSTALL_PREFIX from its own location;
    # capture it before the staging logic below reuses that variable name.
    set(CPPJIT_EXTERNAL_CPPINTEROP_PREFIX "${CPPINTEROP_INSTALL_PREFIX}")
    set(LLVM_VERSION_MAJOR "${CPPINTEROP_LLVM_VERSION_MAJOR}")
    message(STATUS "Using external CppInterOp at ${CPPJIT_EXTERNAL_CPPINTEROP_PREFIX} "
                   "(LLVM ${CPPINTEROP_LLVM_VERSION})")
    # An external CppInterOp bundles no builtin headers, and clang's
    # compiled-in default resolves relative to the library location, so the
    # resource dir should be given explicitly; without it the wrapper falls
    # back to probing PATH for a versioned clang at runtime, which works in
    # e.g. conda environments but not everywhere.
    if(NOT CPPJIT_CLANG_RESOURCE_DIR)
        message(WARNING
            "CPPJIT_CLANG_RESOURCE_DIR not set: the interpreter will probe "
            "PATH for clang-${LLVM_VERSION_MAJOR} at runtime to locate the "
            "builtin headers")
    endif()
else()
    # The LLVM range the pinned CppInterOp supports; update together with the tag.
    set(CPPJIT_LLVM_VERSION_MIN 20)
    set(CPPJIT_LLVM_VERSION_MAX 22)

    set(_llvm_hints "")

    if(DEFINED ENV{CONDA_PREFIX})
        list(APPEND _llvm_hints "$ENV{CONDA_PREFIX}/lib/cmake/llvm")
    endif()

    if(DEFINED LLVM_DIR)
        # An explicit LLVM_DIR is authoritative: fail instead of falling back to a
        # different LLVM than the one requested. A failed find_package resets
        # LLVM_DIR to -NOTFOUND, so keep the requested value for the message.
        set(_llvm_dir_arg "${LLVM_DIR}")
        find_package(LLVM CONFIG PATHS "${LLVM_DIR}" NO_DEFAULT_PATH)
        if(NOT LLVM_FOUND)
            message(FATAL_ERROR
                "No LLVMConfig.cmake under LLVM_DIR (${_llvm_dir_arg}); expected "
                "<install prefix or build tree>/lib/cmake/llvm")
        endif()
    else()
        find_package(LLVM CONFIG QUIET HINTS ${_llvm_hints})
        if(NOT LLVM_FOUND)
            message(FATAL_ERROR
                "No LLVM CMake package found. Install LLVM "
                "${CPPJIT_LLVM_VERSION_MIN}-${CPPJIT_LLVM_VERSION_MAX} development packages "
                "(apt: llvm-${CPPJIT_LLVM_VERSION_MAX}-dev libclang-${CPPJIT_LLVM_VERSION_MAX}-dev; "
                "conda: llvmdev clangdev), or point cppjit at your own LLVM build with "
                "-DLLVM_DIR=<prefix or build tree>/lib/cmake/llvm "
                "(pip: --config-settings=cmake.define.LLVM_DIR=...)")
        endif()
    endif()

    message(STATUS "Found LLVM ${LLVM_VERSION} at ${LLVM_DIR}")
    if(LLVM_VERSION_MAJOR LESS CPPJIT_LLVM_VERSION_MIN OR
       LLVM_VERSION_MAJOR GREATER CPPJIT_LLVM_VERSION_MAX)
        message(FATAL_ERROR
            "LLVM ${LLVM_VERSION} is unsupported: the currently supported "
            "CppInterOp version (${CPPINTEROP_GIT_TAG}) only supports LLVM "
            "${CPPJIT_LLVM_VERSION_MIN}-${CPPJIT_LLVM_VERSION_MAX}")
    endif()

    if(DEFINED Clang_DIR)
        # An explicit Clang_DIR is authoritative, like LLVM_DIR above.
        set(_clang_dir_arg "${Clang_DIR}")
        find_package(Clang CONFIG PATHS "${Clang_DIR}" NO_DEFAULT_PATH)
        if(NOT Clang_FOUND)
            message(FATAL_ERROR
                "No ClangConfig.cmake under Clang_DIR (${_clang_dir_arg}); expected "
                "<install prefix or build tree>/lib/cmake/clang")
        endif()
    else()
        # Clang's package sits beside LLVM's in every supported layout; search
        # only there so an unrelated system clang cannot satisfy the lookup.
        find_package(Clang CONFIG QUIET HINTS "${LLVM_DIR}/../clang" NO_DEFAULT_PATH)
    endif()
    if(Clang_FOUND)
        message(STATUS "Found Clang at ${Clang_DIR}")
    endif()
endif()

# CppInterOp is installed at the location cppjit ships at runtime: ask for the
# site-packages path; fall back to CMAKE_INSTALL_PREFIX for standalone builds.
execute_process(
    COMMAND ${Python_EXECUTABLE} -c "import sysconfig; print(sysconfig.get_path('platlib'))"
    OUTPUT_VARIABLE _python_platlib
    OUTPUT_STRIP_TRAILING_WHITESPACE
)
if(_python_platlib)
    set(CPPINTEROP_INSTALL_PREFIX "${_python_platlib}")
else()
    set(CPPINTEROP_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")
endif()
set(CPPINTEROP_INSTALL_DIR "${CPPINTEROP_INSTALL_PREFIX}/cppjit/interop")

if(CppInterOp_FOUND)
    set(CPPINTEROP_INSTALL_DIR "${CPPJIT_EXTERNAL_CPPINTEROP_PREFIX}")
else()
    # Include cmake for CppInterOp config and build using ExternalProject.
    include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/AddCppInterOp.cmake)
    cppjit_add_cppinterop()
endif()

# this libcppjit.so merges both cpyrt and the interop wrapper
file(GLOB CPYRT_SOURCES CONFIGURE_DEPENDS src/cpyrt/*.cxx)
set(INTEROP_SOURCES
    src/interop/interop_wrapper.cxx
    src/interop/cppinterop_dispatch.cxx
)

add_library(cppjit SHARED ${CPYRT_SOURCES} ${INTEROP_SOURCES})
if(NOT CppInterOp_FOUND)
    add_dependencies(cppjit CppInterOp)
endif()

# The clang resource dir whose builtin headers the interpreter uses. In the
# default bundled mode it must exist (its include/ ships in the wheel); in
# external mode it is optional, falling back to the runtime probe.
set(CPPJIT_CLANG_RESOURCE_DIR "" CACHE PATH
    "clang resource directory whose builtin headers the interpreter uses")
if(NOT CPPJIT_CLANG_RESOURCE_DIR AND NOT CppInterOp_FOUND)
    set(CPPJIT_CLANG_RESOURCE_DIR "${LLVM_LIBRARY_DIR}/clang/${LLVM_VERSION_MAJOR}")
endif()
if(CPPJIT_CLANG_RESOURCE_DIR AND NOT EXISTS "${CPPJIT_CLANG_RESOURCE_DIR}/include")
    message(FATAL_ERROR
        "No builtin headers at ${CPPJIT_CLANG_RESOURCE_DIR}/include")
endif()

if(CppInterOp_FOUND)
    if(CPPJIT_CLANG_RESOURCE_DIR)
        set(_cppjit_clang_include_dir "${CPPJIT_CLANG_RESOURCE_DIR}")
    else()
        # Nothing is bundled and no resource dir was given: use the bundled
        # relative spelling, which resolves nowhere, so the wrapper falls
        # through to the runtime resource-dir probe.
        set(_cppjit_clang_include_dir "interop/lib/clang/${LLVM_VERSION_MAJOR}")
    endif()
    # Absolute spellings from the CppInterOp package config:
    # cppinterop_paths() joins with std::filesystem's /, where an absolute
    # right-hand side replaces the anchor, so the external install and the
    # build clang's resource dir are used in place.
    target_compile_definitions(cppjit PRIVATE
        CPPINTEROP_INSTALL_PREFIX="${CPPJIT_EXTERNAL_CPPINTEROP_PREFIX}"
        CPPINTEROP_LIBRARY="${CPPINTEROP_LIBRARIES}"
        CPPINTEROP_INCLUDE_DIR="${CPPINTEROP_INCLUDE_DIRS}"
        CPPJIT_CLANG_MAJOR="${LLVM_VERSION_MAJOR}"
        CPPJIT_CLANG_INCLUDE_DIR="${_cppjit_clang_include_dir}"
    )
else()
    # The wrapper anchors these relative spellings at its own load location,
    # falling back to the install prefix (see cppinterop_paths()); the clang
    # major names the versioned compiler probed for the runtime resource dir.
    target_compile_definitions(cppjit PRIVATE
        CPPINTEROP_INSTALL_PREFIX="${CPPINTEROP_INSTALL_PREFIX}/cppjit"
        CPPINTEROP_LIBRARY="interop/lib/libclangCppInterOp${CMAKE_SHARED_LIBRARY_SUFFIX}"
        CPPINTEROP_INCLUDE_DIR="interop/include"
        CPPJIT_CLANG_MAJOR="${LLVM_VERSION_MAJOR}"
        CPPJIT_CLANG_INCLUDE_DIR="interop/lib/clang/${LLVM_VERSION_MAJOR}"
    )
endif()

target_include_directories(cppjit PRIVATE
    # src/ itself resolves the public "cpyrt/*.h" spellings against the
    # flattened src/cpyrt/ directory
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/src/cpyrt
    ${CMAKE_CURRENT_SOURCE_DIR}/src/interop
    ${CPPINTEROP_INSTALL_DIR}/include
    ${Python_INCLUDE_DIRS}
)

target_compile_options(cppjit PRIVATE
    -Wall -Wno-strict-aliasing -Wno-register
)

if(CMAKE_COMPILER_IS_GNUCXX)
    target_link_options(cppjit PRIVATE -Wl,-Bsymbolic-functions)
endif()

# macOS needs to allow undefined Python symbols
if(APPLE)
    set_target_properties(cppjit PROPERTIES
        LINK_FLAGS "-undefined dynamic_lookup"
        SUFFIX ".so"
    )
endif()

set_target_properties(cppjit PROPERTIES
    OUTPUT_NAME "cppjit"
    PREFIX "lib"
)

# the extension lives inside the package (import cppjit.libcppjit)
install(TARGETS cppjit
    LIBRARY DESTINATION cppjit
)

# With an external CppInterOp the wrapper references it and the clang resource
# dir at their absolute locations, so nothing needs to be bundled.
if(NOT CppInterOp_FOUND)
    # install CppInterOp libraries and headers
    install(CODE "
        file(GLOB _interop_libs \"${CPPINTEROP_INSTALL_DIR}/lib/libclangCppInterOp*\")
        foreach(_lib \${_interop_libs})
            file(INSTALL \${_lib} DESTINATION \${CMAKE_INSTALL_PREFIX}/cppjit/interop/lib)
        endforeach()
    ")

    install(CODE "
        file(INSTALL \"${CPPINTEROP_INSTALL_DIR}/include/\" DESTINATION \${CMAKE_INSTALL_PREFIX}/cppjit/interop/include)
    ")

    install(DIRECTORY "${CPPJIT_CLANG_RESOURCE_DIR}/include/"
        DESTINATION "cppjit/interop/lib/clang/${LLVM_VERSION_MAJOR}/include"
    )
endif()

# the public cpyrt API headers keep their installed cpyrt/ prefix
install(FILES
    src/cpyrt/API.h
    src/cpyrt/CommonDefs.h
    src/cpyrt/DispatchPtr.h
    src/cpyrt/PyException.h
    src/cpyrt/Reflex.h
    DESTINATION cppjit/interop/include/cpyrt
)
