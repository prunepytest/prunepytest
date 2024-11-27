import pathlib
import sys

import pytest

from builtins import __import__ as builtins_import
from importlib import __import__ as importlib_import
from importlib import import_module

from .tracker_helper import CleanImportTrackerContext


def setup_module() -> None:
    # add the test-data folder to the module search path so we can import our test cases
    test_data_path = str(pathlib.PurePath(__file__).parents[2] / 'test-data')
    if test_data_path not in sys.path:
        sys.path.insert(0, test_data_path)


class TestTracker:

    def test_import_statement(self) -> None:
        with CleanImportTrackerContext('simple', expect_tracked={
            "simple": set(),
            "simple.foo": {'simple'},
            "simple.foo.qux": {'simple', 'simple.foo'},
        }):
            import simple.foo.qux

    def test_import_from_statement_with_module(self) -> None:
        with CleanImportTrackerContext('simple', expect_tracked={
            "simple": set(),
            "simple.foo": {'simple'},
            "simple.foo.qux": {'simple', 'simple.foo'},
        }):
            from simple.foo import qux

    def test_import_from_statement_with_item(self) -> None:
        with CleanImportTrackerContext('simple', expect_tracked={
            "simple": set(),
            "simple.foo": {'simple'},
            "simple.foo.qux": {'simple', 'simple.foo'},
        }):
            from simple.foo.qux import Qux

    @pytest.mark.parametrize("fn", [
        builtins_import,
        importlib_import,
        import_module,
    ])
    def test_import_functions(self, fn) -> None:
        with CleanImportTrackerContext('simple', expect_tracked={
            "simple": set(),
            "simple.foo": {'simple'},
            "simple.foo.qux": {'simple', 'simple.foo'},
        }):
            fn('simple.foo.qux')

    @pytest.mark.parametrize("fn", [
        builtins_import,
        importlib_import,
        import_module,
    ])
    def test_import_baz(self, fn) -> None:
        with CleanImportTrackerContext('simple', expect_tracked={
            "simple": set(),
            "simple.baz": {'simple', 'simple.foo', 'simple.foo.qux'},
            "simple.foo": {'simple'},
            "simple.foo.qux": {'simple', 'simple.foo'},
        }):
            fn('simple.baz')

    @pytest.mark.parametrize("fn", [
        builtins_import,
        importlib_import,
        import_module,
    ])
    def test_import_bar(self, fn) -> None:
        with CleanImportTrackerContext('simple', expect_tracked={
            "simple": set(),
            "simple.bar": {'simple', 'simple.baz', 'simple.foo', 'simple.foo.qux'},
            "simple.baz": {'simple', 'simple.foo', 'simple.foo.qux'},
            "simple.foo": {'simple'},
            "simple.foo.qux": {'simple', 'simple.foo'},
        }):
            fn('simple.bar')


    @pytest.mark.parametrize("fn", [
        builtins_import,
        importlib_import,
        import_module,
    ])
    def test_unresolved(self, fn) -> None:
        with CleanImportTrackerContext('unresolved', expect_tracked={
            "unresolved": {'unresolved'},
        }):
            fn('unresolved')



    @pytest.mark.parametrize("start", [
        "cycles.a_to_b",
        "cycles.b_to_c",
        "cycles.c_to_a",
    ])
    def test_cycle(self, start) -> None:
        with CleanImportTrackerContext('cycles', expect_tracked={
            "cycles": set(),
            "cycles.a_to_b": {"cycles", "cycles.a_to_b", "cycles.b_to_c", "cycles.c_to_a"},
            "cycles.b_to_c": {"cycles", "cycles.a_to_b", "cycles.b_to_c", "cycles.c_to_a"},
            "cycles.c_to_a": {"cycles", "cycles.a_to_b", "cycles.b_to_c", "cycles.c_to_a"}
        }):
            import_module(start)

