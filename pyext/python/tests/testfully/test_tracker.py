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
    def test_cycle_siblings(self, start) -> None:
        with CleanImportTrackerContext('cycles', expect_tracked={
            "cycles": set(),
            "cycles.a_to_b": {"cycles", "cycles.a_to_b", "cycles.b_to_c", "cycles.c_to_a"},
            "cycles.b_to_c": {"cycles", "cycles.a_to_b", "cycles.b_to_c", "cycles.c_to_a"},
            "cycles.c_to_a": {"cycles", "cycles.a_to_b", "cycles.b_to_c", "cycles.c_to_a"}
        }):
            import_module(start)

    @pytest.mark.parametrize("start", [
        "cycles.foo",
        "cycles.foo.bar",
        "cycles.foo.bar.baz",
    ])
    def test_cycle_nested(self, start) -> None:
        with CleanImportTrackerContext('cycles', expect_tracked={
            "cycles": set(),
            "cycles.foo": {"cycles", "cycles.foo", "cycles.foo.bar", "cycles.foo.bar.baz"},
            "cycles.foo.bar": {"cycles", "cycles.foo", "cycles.foo.bar", "cycles.foo.bar.baz"},
            "cycles.foo.bar.baz": {"cycles", "cycles.foo", "cycles.foo.bar", "cycles.foo.bar.baz"}
        }):
            import_module(start)

    def test_repeated_import_stmt(self) -> None:
        with CleanImportTrackerContext('repeated', expect_tracked={
            "repeated": set(),
            "repeated.same": {"repeated", "repeated.old"},
            "repeated.one": {"repeated", "repeated.same", "repeated.old"},
            "repeated.two": {"repeated", "repeated.same", "repeated.old"},
            "repeated.three": {"repeated", "repeated.same", "repeated.old"},
        }):
            import repeated.one
            import repeated.two
            import repeated.three

    @pytest.mark.parametrize("fn", [
        builtins_import,
        importlib_import,
        import_module,
    ])
    def test_repeated_fn(self, fn) -> None:
        with CleanImportTrackerContext('repeated', expect_tracked={
            "repeated": set(),
            "repeated.same": {"repeated", "repeated.old"},
            "repeated.one": {"repeated", "repeated.same", "repeated.old"},
            "repeated.two": {"repeated", "repeated.same", "repeated.old"},
            "repeated.three": {"repeated", "repeated.same", "repeated.old"},
        }):
            fn('repeated.one')
            fn('repeated.two')
            fn('repeated.three')

    @pytest.mark.parametrize("start", [
        "dynamic.foo",
        "dynamic.bar",
        "dynamic.baz",
    ])
    def test_dynamic_with_dynamic_false(self, start) -> None:
        with CleanImportTrackerContext('dynamic', with_dynamic=False, expect_tracked={
            "dynamic": set(),
            "dynamic.indirect": {"dynamic", "dynamic.direct"},
            start: {"dynamic", "dynamic.indirect", "dynamic.direct"}
        }):
            import_module(start)

    @pytest.mark.parametrize("start", [
        "dynamic.foo",
        "dynamic.bar",
        "dynamic.baz",
    ])
    def test_dynamic_with_dynamic_false_order_does_not_matter(self, start) -> None:
        with CleanImportTrackerContext('dynamic', with_dynamic=False, expect_tracked={
            "dynamic": set(),
            "dynamic.indirect": {"dynamic", "dynamic.direct"},
            start: {"dynamic", "dynamic.indirect", "dynamic.direct"}
        }):
            import_module("dynamic.indirect")
            import_module(start)

    @pytest.mark.parametrize("start", [
        "dynamic.foo",
        "dynamic.bar",
        "dynamic.baz",
    ])
    def test_dynamic_with_dynamic_true(self, start) -> None:
        with CleanImportTrackerContext('dynamic', with_dynamic=True, expect_tracked={
            "dynamic": set(),
            "dynamic.indirect": {"dynamic", "dynamic.direct"},
            start: {"dynamic", "dynamic.indirect", "dynamic.direct"},
        }):
            import_module(start)

    @pytest.mark.parametrize("start", [
        "dynamic.foo",
        "dynamic.bar",
        "dynamic.baz",
    ])
    def test_dynamic_with_dynamic_true_order_does_not_matter(self, start) -> None:
        with CleanImportTrackerContext('dynamic', with_dynamic=True, expect_tracked={
            "dynamic": set(),
            "dynamic.indirect": {"dynamic", "dynamic.direct"},
            start: {"dynamic", "dynamic.indirect", "dynamic.direct"}
        }):
            import_module("dynamic.indirect")
            import_module(start)


    def test_dynamic_with_dynamic_false_does_not_combine_all(self) -> None:
        with CleanImportTrackerContext('dynamic', with_dynamic=False, expect_tracked={
            "dynamic": set(),
            f"dynamic._foo": {"dynamic"},
            f"dynamic._bar": {"dynamic"},
            f"dynamic._baz": {"dynamic"},
            f"dynamic.by_caller": {"dynamic"},
            f"dynamic.qux.foo": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._foo"},
            f"dynamic.qux.bar": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._bar"},
            f"dynamic.qux.baz": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._baz"},
        }):
            for start in ['foo', 'bar', 'baz']:
                import_module(f"dynamic.qux.{start}")

    def test_dynamic_with_dynamic_true_combine_all(self) -> None:
        with CleanImportTrackerContext('dynamic', with_dynamic=True, expect_tracked={
            "dynamic": set(),
            f"dynamic._foo": {"dynamic"},
            f"dynamic._bar": {"dynamic"},
            f"dynamic._baz": {"dynamic"},
            f"dynamic.by_caller": {"dynamic"},
            f"dynamic.qux.foo": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._foo", f"dynamic._bar", f"dynamic._baz"},
            f"dynamic.qux.bar": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._foo", f"dynamic._bar", f"dynamic._baz"},
            f"dynamic.qux.baz": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._foo", f"dynamic._bar", f"dynamic._baz"},
        }):
            for start in ['foo', 'bar', 'baz']:
                import_module(f"dynamic.qux.{start}")


