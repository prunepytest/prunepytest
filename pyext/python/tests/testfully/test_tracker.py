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

def test_import_statement() -> None:
    with CleanImportTrackerContext('simple', expect_tracked={
        "simple": set(),
        "simple.foo": {'simple'},
        "simple.foo.qux": {'simple', 'simple.foo'},
    }):
        import simple.foo.qux

def test_import_from_statement_with_module() -> None:
    with CleanImportTrackerContext('simple', expect_tracked={
        "simple": set(),
        "simple.foo": {'simple'},
        "simple.foo.qux": {'simple', 'simple.foo'},
    }):
        from simple.foo import qux

def test_import_from_statement_with_item() -> None:
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
def test_import_functions(fn) -> None:
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
def test_import_simple_transitive(fn) -> None:
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
def test_import_simple_transitive_2(fn) -> None:
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
def test_unresolved(fn) -> None:
    with CleanImportTrackerContext('unresolved', expect_tracked={
        "unresolved": {'unresolved'},
    }):
        fn('unresolved')

@pytest.mark.parametrize("start", [
    "cycles.a_to_b",
    "cycles.b_to_c",
    "cycles.c_to_a",
])
def test_cycle_siblings(start) -> None:
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
def test_cycle_nested(start) -> None:
    with CleanImportTrackerContext('cycles', expect_tracked={
        "cycles": set(),
        "cycles.foo": {"cycles", "cycles.foo", "cycles.foo.bar", "cycles.foo.bar.baz"},
        "cycles.foo.bar": {"cycles", "cycles.foo", "cycles.foo.bar", "cycles.foo.bar.baz"},
        "cycles.foo.bar.baz": {"cycles", "cycles.foo", "cycles.foo.bar", "cycles.foo.bar.baz"}
    }):
        import_module(start)

def test_repeated_import_stmt() -> None:
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

def test_repeated_import_from_stmt() -> None:
    with CleanImportTrackerContext('repeated', expect_tracked={
        "repeated": set(),
        "repeated.same": {"repeated", "repeated.old"},
        "repeated.one": {"repeated", "repeated.same", "repeated.old"},
        "repeated.two": {"repeated", "repeated.same", "repeated.old"},
        "repeated.three": {"repeated", "repeated.same", "repeated.old"},
    }):
        from repeated import one
        from repeated import two
        from repeated import three

@pytest.mark.parametrize("fn", [
    builtins_import,
    importlib_import,
    import_module,
])
def test_repeated_fn(fn) -> None:
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
def test_dynamic_with_dynamic_false(start) -> None:
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
def test_dynamic_with_dynamic_true(start) -> None:
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
def test_dynamic_with_dynamic_false_order_does_not_matter(start) -> None:
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
def test_dynamic_with_dynamic_true_order_does_not_matter(start) -> None:
    with CleanImportTrackerContext('dynamic', with_dynamic=True, expect_tracked={
        "dynamic": set(),
        "dynamic.indirect": {"dynamic", "dynamic.direct"},
        start: {"dynamic", "dynamic.indirect", "dynamic.direct"}
    }):
        import_module("dynamic.indirect")
        import_module(start)

def test_dynamic_with_dynamic_false_does_not_combine_all() -> None:
    with CleanImportTrackerContext(
            'dynamic',
            with_dynamic=False,
            expect_tracked={
                "dynamic": set(),
                f"dynamic._foo": {"dynamic"},
                f"dynamic._bar": {"dynamic"},
                f"dynamic._baz": {"dynamic"},
                f"dynamic.by_caller": {"dynamic"},
                f"dynamic.qux.foo": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._foo"},
                f"dynamic.qux.bar": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._bar"},
                f"dynamic.qux.baz": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._baz"},
                f"dynamic.qux.noop": {"dynamic", "dynamic.qux", "dynamic.by_caller"},
            }
    ):
        for start in ['foo', 'bar', 'baz', 'noop']:
            import_module(f"dynamic.qux.{start}")

def test_dynamic_with_dynamic_true_combine_all() -> None:
    with CleanImportTrackerContext(
            'dynamic',
            with_dynamic=True,
            expect_tracked={
                "dynamic": set(),
                f"dynamic._foo": {"dynamic"},
                f"dynamic._bar": {"dynamic"},
                f"dynamic._baz": {"dynamic"},
                f"dynamic.by_caller": {"dynamic"},
                f"dynamic.qux.foo": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._foo", f"dynamic._bar", f"dynamic._baz"},
                f"dynamic.qux.bar": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._foo", f"dynamic._bar", f"dynamic._baz"},
                f"dynamic.qux.baz": {"dynamic", "dynamic.qux", "dynamic.by_caller", f"dynamic._foo", f"dynamic._bar", f"dynamic._baz"},
                f"dynamic.qux.noop": {"dynamic", "dynamic.qux", "dynamic.by_caller"},
            }
    ):
        for start in ['foo', 'bar', 'baz', 'noop']:
            import_module(f"dynamic.qux.{start}")


def test_dynamic_without_anchor_picks_last() -> None:
    with CleanImportTrackerContext(
            'dynamic',
            with_dynamic=True,
            expect_tracked={
                "dynamic": set(),
                f"dynamic.anchored": {"dynamic"},
                f"dynamic.anchored.a": {"dynamic", "dynamic.anchored", "dynamic.anchored.b", "dynamic.anchored.c", "dynamic.direct"},
                f"dynamic.anchored.b": {"dynamic", "dynamic.anchored", "dynamic.anchored.c"},
                f"dynamic.anchored.c": {"dynamic", "dynamic.anchored"},
                f"dynamic.direct": {"dynamic"},
            }
    ) as c:
        import_module(f"dynamic.anchored.a")
        assert c.tracker.dynamic_imports.get(('dynamic.anchored.c', 'bla')) == {'dynamic.direct'}
        assert c.tracker.dynamic_users.get('dynamic.anchored.a') == {('dynamic.anchored.c', 'bla')}

def test_dynamic_with_anchor_picks_anchor() -> None:
    with CleanImportTrackerContext(
            'dynamic',
            with_dynamic=True,
            dynamic_anchors={
                "dynamic.anchored.b": {"gloop"}
            },
            expect_tracked={
                "dynamic": set(),
                f"dynamic.anchored": {"dynamic"},
                f"dynamic.anchored.a": {"dynamic", "dynamic.anchored", "dynamic.anchored.b", "dynamic.anchored.c", "dynamic.direct"},
                f"dynamic.anchored.b": {"dynamic", "dynamic.anchored", "dynamic.anchored.c"},
                f"dynamic.anchored.c": {"dynamic", "dynamic.anchored"},
                f"dynamic.direct": {"dynamic"},
            }
    ) as c:
        import_module(f"dynamic.anchored.a")
        assert c.tracker.dynamic_imports.get(('dynamic.anchored.b', 'gloop')) == {'dynamic.direct'}, c.tracker.dynamic_imports
        assert c.tracker.dynamic_users.get('dynamic.anchored.a') == {('dynamic.anchored.b', 'gloop')}, c.tracker.dynamic_users


def test_dynamic_with_overlapping_anchors_picks_first() -> None:
    with CleanImportTrackerContext(
            'dynamic',
            with_dynamic=True,
            dynamic_anchors={
                "dynamic.anchored.a": {"lolwut"},
                "dynamic.anchored.b": {"gloop"}
            },
            expect_tracked={
                "dynamic": set(),
                f"dynamic.anchored": {"dynamic"},
                f"dynamic.anchored.a": {"dynamic", "dynamic.anchored", "dynamic.anchored.b", "dynamic.anchored.c", "dynamic.direct"},
                f"dynamic.anchored.b": {"dynamic", "dynamic.anchored", "dynamic.anchored.c"},
                f"dynamic.anchored.c": {"dynamic", "dynamic.anchored"},
                f"dynamic.direct": {"dynamic"},
            }
    ) as c:
        import_module(f"dynamic.anchored.a")
        assert c.tracker.dynamic_imports.get(('dynamic.anchored.a', 'lolwut')) == {'dynamic.direct'}, c.tracker.dynamic_imports
        assert c.tracker.dynamic_users.get('dynamic.anchored.a') == {('dynamic.anchored.a', 'lolwut')}, c.tracker.dynamic_users


def test_apply_patches():
    with CleanImportTrackerContext(
            'simple',
            patches={
                "simple.bar": {
                    "var": lambda _: 'var-patched',
                    "function": lambda _: (lambda: "function-patched"),
                    "_bar.field": lambda _: "field-patched",
                    "Bar.method": lambda _: (lambda self: "method-patched"),
                }
            },
    ):
        from simple import bar
        assert bar.var == "var-patched"
        assert bar.function() == "function-patched"
        assert bar._bar.field == "field-patched"
        assert bar._bar.method() == "method-patched"


def test_handle_from_list_not_module():
    with CleanImportTrackerContext('simple'):
        from simple import __version__


def test_resolve_reexport():
    with CleanImportTrackerContext(
        'reexport',
        expect_tracked={
            'reexport': {'reexport', 'reexport.bar'},
            'reexport.bar': {'reexport', 'reexport.bar'},
            '': {'reexport', 'reexport.bar'}
        }
    ):
        from reexport import baz, qux

def test_dynamic_ignores():
    with CleanImportTrackerContext(
        'dynamic',
        dynamic_ignores={

        }
    ):
        pass
@pytest.mark.parametrize("start", [
    "dynamic.qux.foo",
    "dynamic.qux.bar",
    "dynamic.qux.baz",
])
def test_dynamic_ignores(start) -> None:
    with CleanImportTrackerContext(
        'dynamic',
        with_dynamic=True,
        dynamic_ignores={
            'dynamic.by_caller': {"import_by_name"}
        },
        expect_tracked={
            "dynamic": set(),
            start: {"dynamic", "dynamic.qux", "dynamic.by_caller"}
        }
    ):
        import_module(start)

def test_dynamic_anchors_recorder() -> None:
    with CleanImportTrackerContext(
        'dynamic',
        with_dynamic=True,
        dynamic_anchors={
            'dynamic.by_caller': {"import_by_caller"}
        },
        expect_tracked={
            "dynamic": set(),
            "dynamic.by_caller": {"dynamic"},
            "dynamic.all_qux": {"dynamic", "dynamic.by_caller",
                                "dynamic._foo", "dynamic._bar", "dynamic._baz"},
        }
    ):
        from dynamic import all_qux

def test_dynamic_anchors_recorder_aggregates_from_parent() -> None:
    with CleanImportTrackerContext(
            'dynamic',
            with_dynamic=True,
            dynamic_anchors={
                'dynamic.by_caller': {"import_by_caller"}
            },
            expect_tracked={
                "dynamic": set(),
                "dynamic.by_caller": {"dynamic"},
                "dynamic.all_qux": {"dynamic", "dynamic.by_caller",
                                    "dynamic._foo", "dynamic._bar", "dynamic._baz"},
                "dynamic.all_qux.and_more": {"dynamic", "dynamic.all_qux", "dynamic.by_caller",
                                    "dynamic._foo", "dynamic._bar", "dynamic._baz"},
            }
    ):
        from dynamic import all_qux
        from dynamic.all_qux import and_more

def test_dynamic_anchors_recorder_method() -> None:
    with CleanImportTrackerContext(
            'dynamic',
            with_dynamic=True,
            dynamic_anchors={
                'dynamic.by_caller': {"Importer.by_name"}
            },
            expect_tracked={
                "dynamic": set(),
                "dynamic.by_caller": {"dynamic"},
                "dynamic.all_qux2": {"dynamic", "dynamic.by_caller",
                                    "dynamic._foo", "dynamic._bar", "dynamic._baz"},
            }
    ):
        from dynamic import all_qux2
        all_qux2.all()

def test_dynamic_anchors_recorder_field() -> None:
    with CleanImportTrackerContext(
            'dynamic',
            with_dynamic=True,
            dynamic_anchors={
                'dynamic.by_caller': {"importer.by_name"}
            },
            expect_tracked={
                "dynamic": set(),
                "dynamic.by_caller": {"dynamic"},
                "dynamic.all_qux2": {"dynamic", "dynamic.by_caller",
                                    "dynamic._foo", "dynamic._bar", "dynamic._baz"},
            }
    ):
        from dynamic import all_qux2
        all_qux2.all()
