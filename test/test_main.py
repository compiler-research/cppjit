if __name__ == "__main__":
    import sys

    # Bazel-only runtime path fixups. The py_test bootstrap builds sys.path
    # in-process, so `site` cannot auto-import them; import them here instead.
    # No such module in a pip/CMake run.
    try:
        import sitecustomize  # noqa: F401
    except ImportError:
        pass

    import pytest

    sys.exit(pytest.main())
