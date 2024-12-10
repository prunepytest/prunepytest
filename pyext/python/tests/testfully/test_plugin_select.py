import os.path
import pathlib

from _pytest._code import Source


def write_text(path, content):
    path.write_text(str(Source(content)))


def test_plugin_select_noop(pytester):
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
    result = pytester.runpytest("--testfully", "--tf-modified=")
    result.assert_outcomes()


def test_plugin_select_code(pytester):
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
    result = pytester.runpytest(
        "--testfully", "--tf-modified=" + os.path.join("blah", "stuff.py")
    )
    result.assert_outcomes(passed=1)


def test_plugin_select_test(pytester):
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
    result = pytester.runpytest(
        "--testfully", "--tf-modified=" + os.path.join("blah", "stuff.py")
    )
    result.assert_outcomes(passed=1)


# TODO: test within a git repo
# TODO: test selection
# TODO: more elaborate tests with complex import graphs
