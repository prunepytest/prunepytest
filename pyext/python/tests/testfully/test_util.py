# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

import os.path

from testfully.util import infer_ns_pkg, find_package_roots, hook_zeroconf

from .conftest import TEST_DATA

expected_test_data_pkg = {
    "cycles",
    "dynamic",
    "ns",
    "nsbranching",
    "nsempty",
    "reexport",
    "repeated",
    "simple",
    "unresolved",
}

expected_test_data_dirs = {TEST_DATA / pkg for pkg in expected_test_data_pkg}


def test_infer_ns_pkg() -> None:
    # regular packages
    assert infer_ns_pkg(TEST_DATA / "simple") == (TEST_DATA / "simple", "simple")
    assert infer_ns_pkg(TEST_DATA / "cycles") == (TEST_DATA / "cycles", "cycles")

    # pkgutil-style ns packages
    assert infer_ns_pkg(TEST_DATA / "ns") == (
        TEST_DATA / "ns" / "ns2" / "normal",
        "ns.ns2.normal",
    )
    assert infer_ns_pkg(TEST_DATA / "ns" / "ns2") == (
        TEST_DATA / "ns" / "ns2" / "normal",
        "ns2.normal",
    )
    assert infer_ns_pkg(TEST_DATA / "ns" / "ns2" / "normal") == (
        TEST_DATA / "ns" / "ns2" / "normal",
        "normal",
    )

    # multiple sub-ns: bail
    assert infer_ns_pkg(TEST_DATA / "nsbranching") == (
        TEST_DATA / "nsbranching",
        "nsbranching",
    )

    # no non-ns package to find: bail
    assert infer_ns_pkg(TEST_DATA / "nsempty") == (TEST_DATA / "nsempty", "nsempty")


def test_find_package_roots() -> None:
    assert find_package_roots(TEST_DATA) == expected_test_data_dirs

    python_dir = TEST_DATA.parent
    assert (
        find_package_roots(python_dir)
        == {python_dir / "src/testfully", python_dir / "tests"}
        | expected_test_data_dirs
    )

    pyext_dir = python_dir.parent
    assert (
        find_package_roots(pyext_dir)
        == {python_dir / "src/testfully", python_dir / "tests"}
        | expected_test_data_dirs
    )


def test_hook_zeroconf() -> None:
    python_dir = TEST_DATA.parent
    hook = hook_zeroconf(python_dir)

    assert hook.global_namespaces() == {"testfully"} | expected_test_data_pkg
    assert hook.local_namespaces() == {"tests"}
    assert hook.source_roots() == {
        os.path.join("src", "testfully"): "testfully",
        "tests": "tests",
        os.path.join("test-data", "ns", "ns2", "normal"): "ns.ns2.normal",
        **{
            os.path.join("test-data", pkg): pkg
            for pkg in expected_test_data_pkg
            if pkg != "ns"
        },
    }
    assert hook.test_folders() == {"tests": "tests"}

    pyext_dir = python_dir.parent
    hook = hook_zeroconf(pyext_dir)

    assert hook.global_namespaces() == {"testfully"} | expected_test_data_pkg
    assert hook.local_namespaces() == {"tests"}
    assert hook.source_roots() == {
        os.path.join("python", "src", "testfully"): "testfully",
        os.path.join("python", "tests"): "tests",
        os.path.join("python", "test-data", "ns", "ns2", "normal"): "ns.ns2.normal",
        **{
            os.path.join("python", "test-data", pkg): pkg
            for pkg in expected_test_data_pkg
            if pkg != "ns"
        },
    }
    assert hook.test_folders() == {os.path.join("python", "tests"): "tests"}
