import pathlib

from _pytest._code import Source


def write_text(path, content):
    path.write_text(str(Source(content)))


def test_plugin_validate_fail_static_test_file_not_in_graph(pytester):
    pytester.mkpydir("blah")
    pytester.makepyfile(
        """
        def test_noop():
            import blah
        """
    )
    pytester.plugins = ["testfully"]
    result = pytester.runpytest("--testfully", "--tf-noselect")
    result.assert_outcomes(failed=1)


def test_plugin_validate_fail_dynamic_test_file_not_in_graph(pytester):
    pytester.mkpydir("blah")
    pytester.makepyfile(
        """
        def test_noop():
            __import__('blah')
        """
    )
    pytester.plugins = ["testfully"]
    result = pytester.runpytest("--testfully", "--tf-noselect")
    result.assert_outcomes(failed=1)


def test_plugin_validate_succeed_test_file_in_graph_static_import(pytester):
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
    pytester.plugins = ["testfully"]
    result = pytester.runpytest("--testfully", "--tf-noselect")
    result.assert_outcomes(passed=1)


def test_plugin_validate_fail_test_file_in_graph_dynamic_import(pytester):
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
    pytester.plugins = ["testfully"]
    result = pytester.runpytest("--testfully", "--tf-noselect")
    result.assert_outcomes(failed=1)


# TODO: test within a git repo
# TODO: test selection
