import io

import pytest

from builtins import __import__ as builtins_import
from importlib import __import__ as importlib_import
from importlib import import_module

from .tracker_helper import CleanImportTrackerContext
from testfully.tracker import Tracker


def test_import_statement() -> None:
    with CleanImportTrackerContext(
        "simple",
        expect_tracked={
            "simple": set(),
            "simple.foo": {"simple"},
            "simple.foo.qux": {"simple", "simple.foo"},
        },
    ):
        import simple.foo.qux  # noqa: F401


def test_import_from_statement_with_module() -> None:
    with CleanImportTrackerContext(
        "simple",
        expect_tracked={
            "simple": set(),
            "simple.foo": {"simple"},
            "simple.foo.qux": {"simple", "simple.foo"},
        },
    ):
        from simple.foo import qux  # noqa: F401


def test_import_from_statement_with_item() -> None:
    with CleanImportTrackerContext(
        "simple",
        expect_tracked={
            "simple": set(),
            "simple.foo": {"simple"},
            "simple.foo.qux": {"simple", "simple.foo"},
        },
    ):
        from simple.foo.qux import Qux  # noqa: F401


@pytest.mark.parametrize(
    "fn",
    [
        builtins_import,
        importlib_import,
        import_module,
    ],
)
def test_import_functions(fn) -> None:
    with CleanImportTrackerContext(
        "simple",
        expect_tracked={
            "simple": set(),
            "simple.foo": {"simple"},
            "simple.foo.qux": {"simple", "simple.foo"},
        },
    ):
        fn("simple.foo.qux")


@pytest.mark.parametrize(
    "fn",
    [
        builtins_import,
        importlib_import,
        import_module,
    ],
)
def test_import_simple_transitive(fn) -> None:
    with CleanImportTrackerContext(
        "simple",
        expect_tracked={
            "simple": set(),
            "simple.baz": {"simple", "simple.foo", "simple.foo.qux"},
            "simple.foo": {"simple"},
            "simple.foo.qux": {"simple", "simple.foo"},
        },
    ):
        fn("simple.baz")


@pytest.mark.parametrize(
    "fn",
    [
        builtins_import,
        importlib_import,
        import_module,
    ],
)
def test_import_simple_transitive_2(fn) -> None:
    with CleanImportTrackerContext(
        "simple",
        expect_tracked={
            "simple": set(),
            "simple.bar": {"simple", "simple.baz", "simple.foo", "simple.foo.qux"},
            "simple.baz": {"simple", "simple.foo", "simple.foo.qux"},
            "simple.foo": {"simple"},
            "simple.foo.qux": {"simple", "simple.foo"},
        },
    ):
        fn("simple.bar")


@pytest.mark.parametrize(
    "fn",
    [
        builtins_import,
        importlib_import,
        import_module,
    ],
)
def test_unresolved(fn) -> None:
    with CleanImportTrackerContext(
        "unresolved",
        expect_tracked={
            "unresolved": {"unresolved"},
        },
    ):
        fn("unresolved")


@pytest.mark.parametrize(
    "start",
    [
        "cycles.a_to_b",
        "cycles.b_to_c",
        "cycles.c_to_a",
    ],
)
def test_cycle_siblings(start) -> None:
    with CleanImportTrackerContext(
        "cycles",
        expect_tracked={
            "cycles": set(),
            "cycles.a_to_b": {
                "cycles",
                "cycles.a_to_b",
                "cycles.b_to_c",
                "cycles.c_to_a",
            },
            "cycles.b_to_c": {
                "cycles",
                "cycles.a_to_b",
                "cycles.b_to_c",
                "cycles.c_to_a",
            },
            "cycles.c_to_a": {
                "cycles",
                "cycles.a_to_b",
                "cycles.b_to_c",
                "cycles.c_to_a",
            },
        },
    ):
        import_module(start)


@pytest.mark.parametrize(
    "start",
    [
        "cycles.foo",
        "cycles.foo.bar",
        "cycles.foo.bar.baz",
    ],
)
def test_cycle_nested(start) -> None:
    with CleanImportTrackerContext(
        "cycles",
        expect_tracked={
            "cycles": set(),
            "cycles.foo": {
                "cycles",
                "cycles.foo",
                "cycles.foo.bar",
                "cycles.foo.bar.baz",
            },
            "cycles.foo.bar": {
                "cycles",
                "cycles.foo",
                "cycles.foo.bar",
                "cycles.foo.bar.baz",
            },
            "cycles.foo.bar.baz": {
                "cycles",
                "cycles.foo",
                "cycles.foo.bar",
                "cycles.foo.bar.baz",
            },
        },
    ):
        import_module(start)


def test_repeated_import_stmt() -> None:
    with CleanImportTrackerContext(
        "repeated",
        expect_tracked={
            "repeated": set(),
            "repeated.same": {"repeated", "repeated.old"},
            "repeated.one": {"repeated", "repeated.same", "repeated.old"},
            "repeated.two": {"repeated", "repeated.same", "repeated.old"},
            "repeated.three": {"repeated", "repeated.same", "repeated.old"},
        },
    ):
        import repeated.one  # noqa: F401
        import repeated.two  # noqa: F401
        import repeated.three  # noqa: F401


def test_repeated_import_from_stmt() -> None:
    with CleanImportTrackerContext(
        "repeated",
        expect_tracked={
            "repeated": set(),
            "repeated.same": {"repeated", "repeated.old"},
            "repeated.one": {"repeated", "repeated.same", "repeated.old"},
            "repeated.two": {"repeated", "repeated.same", "repeated.old"},
            "repeated.three": {"repeated", "repeated.same", "repeated.old"},
        },
    ):
        from repeated import one  # noqa: F401
        from repeated import two  # noqa: F401
        from repeated import three  # noqa: F401


@pytest.mark.parametrize(
    "fn",
    [
        builtins_import,
        importlib_import,
        import_module,
    ],
)
def test_repeated_fn(fn) -> None:
    with CleanImportTrackerContext(
        "repeated",
        expect_tracked={
            "repeated": set(),
            "repeated.same": {"repeated", "repeated.old"},
            "repeated.one": {"repeated", "repeated.same", "repeated.old"},
            "repeated.two": {"repeated", "repeated.same", "repeated.old"},
            "repeated.three": {"repeated", "repeated.same", "repeated.old"},
        },
    ):
        fn("repeated.one")
        fn("repeated.two")
        fn("repeated.three")


@pytest.mark.parametrize(
    "start",
    [
        "dynamic.foo",
        "dynamic.bar",
        "dynamic.baz",
    ],
)
def test_dynamic_with_dynamic_false(start) -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=False,
        expect_tracked={
            "dynamic": set(),
            "dynamic.indirect": {"dynamic", "dynamic.direct"},
            start: {"dynamic", "dynamic.indirect", "dynamic.direct"},
        },
    ):
        import_module(start)


@pytest.mark.parametrize(
    "start",
    [
        "dynamic.foo",
        "dynamic.bar",
        "dynamic.baz",
    ],
)
def test_dynamic_with_dynamic_true(start) -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        expect_tracked={
            "dynamic": set(),
            "dynamic.indirect": {"dynamic", "dynamic.direct"},
            start: {"dynamic", "dynamic.indirect", "dynamic.direct"},
        },
    ):
        import_module(start)


@pytest.mark.parametrize(
    "start",
    [
        "dynamic.foo",
        "dynamic.bar",
        "dynamic.baz",
    ],
)
def test_dynamic_with_dynamic_false_order_does_not_matter(start) -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=False,
        expect_tracked={
            "dynamic": set(),
            "dynamic.indirect": {"dynamic", "dynamic.direct"},
            start: {"dynamic", "dynamic.indirect", "dynamic.direct"},
        },
    ):
        import_module("dynamic.indirect")
        import_module(start)


@pytest.mark.parametrize(
    "start",
    [
        "dynamic.foo",
        "dynamic.bar",
        "dynamic.baz",
    ],
)
def test_dynamic_with_dynamic_true_order_does_not_matter(start) -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        expect_tracked={
            "dynamic": set(),
            "dynamic.indirect": {"dynamic", "dynamic.direct"},
            start: {"dynamic", "dynamic.indirect", "dynamic.direct"},
        },
    ):
        import_module("dynamic.indirect")
        import_module(start)


def test_dynamic_with_dynamic_false_does_not_combine_all() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=False,
        expect_tracked={
            "dynamic": set(),
            "dynamic._foo": {"dynamic"},
            "dynamic._bar": {"dynamic"},
            "dynamic._baz": {"dynamic"},
            "dynamic.by_caller": {"dynamic"},
            "dynamic.qux.foo": {
                "dynamic",
                "dynamic.qux",
                "dynamic.by_caller",
                "dynamic._foo",
            },
            "dynamic.qux.bar": {
                "dynamic",
                "dynamic.qux",
                "dynamic.by_caller",
                "dynamic._bar",
            },
            "dynamic.qux.baz": {
                "dynamic",
                "dynamic.qux",
                "dynamic.by_caller",
                "dynamic._baz",
            },
            "dynamic.qux.noop": {"dynamic", "dynamic.qux", "dynamic.by_caller"},
        },
    ):
        for start in ["foo", "bar", "baz", "noop"]:
            import_module(f"dynamic.qux.{start}")


def test_dynamic_with_dynamic_true_combine_all() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        expect_tracked={
            "dynamic": set(),
            "dynamic._foo": {"dynamic"},
            "dynamic._bar": {"dynamic"},
            "dynamic._baz": {"dynamic"},
            "dynamic.by_caller": {"dynamic"},
            "dynamic.qux.foo": {
                "dynamic",
                "dynamic.qux",
                "dynamic.by_caller",
                "dynamic._foo",
                "dynamic._bar",
                "dynamic._baz",
            },
            "dynamic.qux.bar": {
                "dynamic",
                "dynamic.qux",
                "dynamic.by_caller",
                "dynamic._foo",
                "dynamic._bar",
                "dynamic._baz",
            },
            "dynamic.qux.baz": {
                "dynamic",
                "dynamic.qux",
                "dynamic.by_caller",
                "dynamic._foo",
                "dynamic._bar",
                "dynamic._baz",
            },
            "dynamic.qux.noop": {"dynamic", "dynamic.qux", "dynamic.by_caller"},
        },
    ):
        for start in ["foo", "bar", "baz", "noop"]:
            import_module(f"dynamic.qux.{start}")


def test_dynamic_without_anchor_picks_last() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        expect_tracked={
            "dynamic": set(),
            "dynamic.anchored": {"dynamic"},
            "dynamic.anchored.a": {
                "dynamic",
                "dynamic.anchored",
                "dynamic.anchored.b",
                "dynamic.anchored.c",
                "dynamic.direct",
            },
            "dynamic.anchored.b": {"dynamic", "dynamic.anchored", "dynamic.anchored.c"},
            "dynamic.anchored.c": {"dynamic", "dynamic.anchored"},
            "dynamic.direct": {"dynamic"},
        },
    ) as c:
        import_module("dynamic.anchored.a")
        assert c.tracker.dynamic_imports.get(("dynamic.anchored.c", "bla")) == {
            "dynamic.direct"
        }
        assert c.tracker.dynamic_users.get("dynamic.anchored.a") == {
            ("dynamic.anchored.c", "bla")
        }


def test_dynamic_with_anchor_picks_anchor() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_anchors={"dynamic.anchored.b": {"gloop"}},
        expect_tracked={
            "dynamic": set(),
            "dynamic.anchored": {"dynamic"},
            "dynamic.anchored.a": {
                "dynamic",
                "dynamic.anchored",
                "dynamic.anchored.b",
                "dynamic.anchored.c",
                "dynamic.direct",
            },
            "dynamic.anchored.b": {"dynamic", "dynamic.anchored", "dynamic.anchored.c"},
            "dynamic.anchored.c": {"dynamic", "dynamic.anchored"},
            "dynamic.direct": {"dynamic"},
        },
    ) as c:
        import_module("dynamic.anchored.a")
        assert c.tracker.dynamic_imports.get(("dynamic.anchored.b", "gloop")) == {
            "dynamic.direct"
        }, c.tracker.dynamic_imports
        assert c.tracker.dynamic_users.get("dynamic.anchored.a") == {
            ("dynamic.anchored.b", "gloop")
        }, c.tracker.dynamic_users


def test_dynamic_with_overlapping_anchors_picks_first() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_anchors={
            "dynamic.anchored.a": {"lolwut"},
            "dynamic.anchored.b": {"gloop"},
        },
        expect_tracked={
            "dynamic": set(),
            "dynamic.anchored": {"dynamic"},
            "dynamic.anchored.a": {
                "dynamic",
                "dynamic.anchored",
                "dynamic.anchored.b",
                "dynamic.anchored.c",
                "dynamic.direct",
            },
            "dynamic.anchored.b": {"dynamic", "dynamic.anchored", "dynamic.anchored.c"},
            "dynamic.anchored.c": {"dynamic", "dynamic.anchored"},
            "dynamic.direct": {"dynamic"},
        },
    ) as c:
        import_module("dynamic.anchored.a")
        assert c.tracker.dynamic_imports.get(("dynamic.anchored.a", "lolwut")) == {
            "dynamic.direct"
        }, c.tracker.dynamic_imports
        assert c.tracker.dynamic_users.get("dynamic.anchored.a") == {
            ("dynamic.anchored.a", "lolwut")
        }, c.tracker.dynamic_users


def test_apply_patches():
    with CleanImportTrackerContext(
        "simple",
        patches={
            "simple.bar": {
                "var": lambda _: "var-patched",
                "function": lambda _: (lambda: "function-patched"),
                "_bar.field": lambda _: "field-patched",
                "Bar.method": lambda _: (lambda self: "method-patched"),
            }
        },
    ):
        from simple import bar  # noqa: F401

        assert bar.var == "var-patched"
        assert bar.function() == "function-patched"
        assert bar._bar.field == "field-patched"
        assert bar._bar.method() == "method-patched"


def test_handle_from_list_not_module():
    with CleanImportTrackerContext("simple"):
        from simple import __version__  # noqa: F401


def test_resolve_reexport():
    with CleanImportTrackerContext(
        "reexport",
        expect_tracked={
            "reexport": {"reexport", "reexport.bar"},
            "reexport.bar": {"reexport", "reexport.bar"},
            "": {"reexport", "reexport.bar"},
        },
    ):
        from reexport import baz, qux  # noqa: F401


@pytest.mark.parametrize(
    "start",
    [
        "dynamic.qux.foo",
        "dynamic.qux.bar",
        "dynamic.qux.baz",
    ],
)
def test_dynamic_ignores(start) -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_ignores={"dynamic.by_caller": {"import_by_name"}},
        expect_tracked={
            "dynamic": set(),
            start: {"dynamic", "dynamic.qux", "dynamic.by_caller"},
        },
    ):
        import_module(start)


def test_dynamic_anchors_recorder() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_anchors={"dynamic.by_caller": {"import_by_name"}},
        expect_tracked={
            "dynamic": set(),
            "dynamic.by_caller": {"dynamic"},
            "dynamic.all_qux": {
                "dynamic",
                "dynamic.by_caller",
                "dynamic._foo",
                "dynamic._bar",
                "dynamic._baz",
            },
        },
    ):
        from dynamic import all_qux  # noqa: F401


def test_dynamic_ignore_overrides_anchors_same() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_ignores={"dynamic.by_caller": {"import_by_name"}},
        dynamic_anchors={"dynamic.by_caller": {"import_by_name"}},
        expect_tracked={
            "dynamic": set(),
            "dynamic.by_caller": {"dynamic"},
            "dynamic.all_qux2": {
                "dynamic",
                "dynamic.by_caller",
            },
        },
    ):
        from dynamic import all_qux2  # noqa: F401


def test_dynamic_ignore_overrides_anchors_before() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_ignores={"dynamic.by_caller": {"import_by_name"}},
        dynamic_anchors={"dynamic.by_caller": {"Importer.by_name"}},
        expect_tracked={
            "dynamic": set(),
            "dynamic.by_caller": {"dynamic"},
            "dynamic.all_qux2": {
                "dynamic",
                "dynamic.by_caller",
            },
        },
    ):
        from dynamic import all_qux2  # noqa: F401


def test_dynamic_ignore_overrides_anchors_after() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_ignores={"dynamic.by_caller": {"Importer.by_name"}},
        dynamic_anchors={"dynamic.by_caller": {"import_by_name"}},
        expect_tracked={
            "dynamic": set(),
            "dynamic.by_caller": {"dynamic"},
            "dynamic.all_qux2": {
                "dynamic",
                "dynamic.by_caller",
            },
        },
    ):
        from dynamic import all_qux2  # noqa: F401


def test_dynamic_anchors_recorder_aggregates_from_parent() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_anchors={"dynamic.by_caller": {"import_by_name"}},
        expect_tracked={
            "dynamic": set(),
            "dynamic.by_caller": {"dynamic"},
            "dynamic.all_qux": {
                "dynamic",
                "dynamic.by_caller",
                "dynamic._foo",
                "dynamic._bar",
                "dynamic._baz",
            },
            "dynamic.all_qux.and_more": {
                "dynamic",
                "dynamic.all_qux",
                "dynamic.by_caller",
                "dynamic._foo",
                "dynamic._bar",
                "dynamic._baz",
            },
        },
    ):
        from dynamic import all_qux  # noqa: F401
        from dynamic.all_qux import and_more  # noqa: F401


def test_dynamic_anchors_recorder_method() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_anchors={"dynamic.by_caller": {"Importer.by_name"}},
        expect_tracked={
            "dynamic": set(),
            "dynamic.by_caller": {"dynamic"},
            "dynamic.all_qux2": {
                "dynamic",
                "dynamic.by_caller",
                "dynamic._foo",
                "dynamic._bar",
                "dynamic._baz",
            },
        },
    ):
        from dynamic import all_qux2  # noqa: F401

        all_qux2.all()


def test_dynamic_anchors_recorder_field() -> None:
    with CleanImportTrackerContext(
        "dynamic",
        with_dynamic=True,
        dynamic_anchors={"dynamic.by_caller": {"importer.by_name"}},
        expect_tracked={
            "dynamic": set(),
            "dynamic.by_caller": {"dynamic"},
            "dynamic.all_qux2": {
                "dynamic",
                "dynamic.by_caller",
                "dynamic._foo",
                "dynamic._bar",
                "dynamic._baz",
            },
        },
    ):
        from dynamic import all_qux2  # noqa: F401

        all_qux2.all()


def test_enter_exit_context() -> None:
    with CleanImportTrackerContext(
        "simple",
        expect_tracked={
            "": {"simple", "simple.foo"},
            "whatsit": {"simple", "simple.foo"},
            "simple": set(),
            "simple.foo": {"simple"},
        },
    ) as cxt:
        cxt.tracker.enter_context("whatsit")
        from simple import foo  # noqa: F401

        cxt.tracker.exit_context("whatsit")


def test_enter_exit_context_must_match() -> None:
    with CleanImportTrackerContext("simple") as cxt:
        cxt.tracker.enter_context("whatsit")
        with pytest.raises(AssertionError):
            cxt.tracker.exit_context("notsame")


def test_register_dynamic_recorder_for_previously_imported():
    # NB: cannot use the clean context here...
    t = Tracker()

    # import before tracking, to exercise patching of already-imported modules
    from dynamic import by_caller  # noqa: F401

    details = io.StringIO()
    t.start_tracking(
        {"dynamic"},
        record_dynamic=True,
        dynamic_anchors={"dynamic.by_caller": {"import_by_name"}},
        log_file=details,
    )

    try:
        from dynamic import all_qux2  # noqa: F401

        assert t.tracked["dynamic.all_qux2"] == {"dynamic", "dynamic.by_caller"}
        assert t.dynamic_users == {}
        assert t.dynamic_imports == {}

        all_qux2.all()

        assert t.with_dynamic("dynamic.all_qux2") == {
            "dynamic",
            "dynamic.by_caller",
            "dynamic._foo",
            "dynamic._bar",
            "dynamic._baz",
        }
    except BaseException:
        print(details.getvalue())
        raise
