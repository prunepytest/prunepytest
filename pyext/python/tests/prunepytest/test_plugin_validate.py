# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

import pathlib

from _pytest._code import Source
from prunepytest.util import load_import_graph, hook_default


# for the import parser
if False:
    from prunepytest.pytest import plugin  # noqa


def write_text(path, content):
    path.write_text(str(Source(content)))


def test_fail_static_test_file_not_in_graph(pytester):
    pytester.mkpydir("blah")
    pytester.makepyfile(
        """
        def test_noop():
            import blah
        """
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select")
    result.assert_outcomes(passed=1)


def test_warn_static_test_file_not_in_graph(pytester):
    pytester.mkpydir("blah")
    pytester.makepyfile(
        """
        def test_noop():
            import blah
        """
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select", "--prune-no-fail")
    result.assert_outcomes(passed=1)


def test_fail_dynamic_test_file_not_in_graph(pytester):
    pytester.mkpydir("blah")
    pytester.makepyfile(
        """
        def test_noop():
            __import__('blah')
        """
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select")
    result.assert_outcomes(passed=1)


def test_warn_dynamic_test_file_not_in_graph(pytester):
    pytester.mkpydir("blah")
    pytester.makepyfile(
        """
        def test_noop():
            __import__('blah')
        """
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select", "--prune-no-fail")
    result.assert_outcomes(passed=1)


def test_succeed_test_file_in_graph_static_import(pytester):
    blah: pathlib.Path = pytester.mkpydir("blah")
    write_text(
        blah.joinpath("stuff.py"),
        """
        """,
    )
    write_text(
        blah.joinpath("test_stuff.py"),
        """
        def test_noop():
             import blah.stuff
        """,
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select")
    result.assert_outcomes(passed=1)


def test_succeed_test_file_in_graph_statically_resolved_dynamic_import(pytester):
    blah: pathlib.Path = pytester.mkpydir("blah")
    write_text(
        blah.joinpath("stuff.py"),
        """
        """,
    )
    write_text(
        blah.joinpath("test_stuff.py"),
        """
        def test_noop():
             __import__('blah.stuff')
        """,
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select")
    result.assert_outcomes(passed=1)


def test_succeed_test_file_in_graph_statically_resolved_dynamic_import_2(pytester):
    blah: pathlib.Path = pytester.mkpydir("blah")
    write_text(
        blah.joinpath("stuff.py"),
        """
        """,
    )
    write_text(
        blah.joinpath("test_stuff.py"),
        """
        import importlib
        def test_noop():
             importlib.import_module('blah.stuff')
        """,
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select")
    result.assert_outcomes(passed=1)


def test_fail_test_file_in_graph_dynamic_import(pytester):
    blah: pathlib.Path = pytester.mkpydir("blah")
    write_text(
        blah.joinpath("stuff.py"),
        """
        """,
    )
    write_text(
        blah.joinpath("test_stuff.py"),
        """
        def test_noop():
             x = 'blah.stuff'
             __import__(x)
        """,
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select")
    result.assert_outcomes(failed=1)


def test_warn_test_file_in_graph_dynamic_import(pytester):
    blah: pathlib.Path = pytester.mkpydir("blah")
    write_text(
        blah.joinpath("stuff.py"),
        """
        """,
    )
    write_text(
        blah.joinpath("test_stuff.py"),
        """
        def test_noop():
             x = 'blah.stuff'
             __import__(x)
        """,
    )
    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest("--prune", "--prune-no-select", "--prune-no-fail")
    result.assert_outcomes(passed=1, warnings=1)


def test_load_existing_graph(pytester):
    blah: pathlib.Path = pytester.mkpydir("blah")
    write_text(
        blah.joinpath("stuff.py"),
        """
        """,
    )
    write_text(
        blah.joinpath("test_stuff.py"),
        """
        def test_noop():
             import blah.stuff
        """,
    )

    hook = hook_default(pytester.path)
    load_import_graph(hook).to_file("graph.bin")

    pytester.plugins = ["prunepytest"]
    result = pytester.runpytest(
        "--prune", "--prune-no-select", "--prune-graph=graph.bin"
    )
    result.assert_outcomes(passed=1)
