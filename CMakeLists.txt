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
set(CPPINTEROP_GIT_REPOSITORY "https://github.com/keremsahn/CppInterOp.git" CACHE STRING "")
set(CPPINTEROP_GIT_TAG "attr-design" CACHE STRING "")
set(CPPINTEROP_SOURCE_DIR "" CACHE PATH
    "Override default CppInterOp built by ExternalProject_Add, with a path to local CppInterOp source")

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

# CppInterOp installs here; cppjit's own rules ship a subset, so the wheel
# owns every installed file.
set(CPPINTEROP_STAGE_DIR "${CMAKE_BINARY_DIR}/cppinterop-stage")

# Include cmake for CppInterOp config and build using ExternalProject.
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/AddCppInterOp.cmake)
cppjit_add_cppinterop()

# this libcppjit.so merges both cpyrt and the interop wrapper
file(GLOB CPYRT_SOURCES CONFIGURE_DEPENDS src/cpyrt/*.cxx)
set(INTEROP_SOURCES
    src/interop/interop_wrapper.cxx
    src/interop/cppinterop_dispatch.cxx
)

add_library(cppjit SHARED ${CPYRT_SOURCES} ${INTEROP_SOURCES})
add_dependencies(cppjit CppInterOp)

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

target_include_directories(cppjit PRIVATE
    # src/ itself resolves the public "cpyrt/*.h" spellings against the
    # flattened src/cpyrt/ directory
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/src/cpyrt
    ${CMAKE_CURRENT_SOURCE_DIR}/src/interop
    ${CPPINTEROP_STAGE_DIR}/include
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

install(DIRECTORY "${CPPINTEROP_STAGE_DIR}/lib/"
    DESTINATION cppjit/interop/lib
)
install(DIRECTORY "${CPPINTEROP_STAGE_DIR}/include/"
    DESTINATION cppjit/interop/include
)

# ship the builtin headers of the build clang, laid out as a headers-only
# resource dir: only include/ ships
set(_clang_resource_dir "${LLVM_LIBRARY_DIR}/clang/${LLVM_VERSION_MAJOR}")
if(NOT EXISTS "${_clang_resource_dir}/include")
    message(FATAL_ERROR
        "No builtin headers at ${_clang_resource_dir}/include; the LLVM at "
        "${LLVM_DIR} carries no clang resource directory")
endif()
install(DIRECTORY "${_clang_resource_dir}/include/"
    DESTINATION "cppjit/interop/lib/clang/${LLVM_VERSION_MAJOR}/include"
)

# the public cpyrt API headers keep their installed cpyrt/ prefix
install(FILES
    src/cpyrt/API.h
    src/cpyrt/CommonDefs.h
    src/cpyrt/DispatchPtr.h
    src/cpyrt/PyException.h
    src/cpyrt/Reflex.h
    DESTINATION cppjit/interop/include/cpyrt
)
