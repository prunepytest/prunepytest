import os.path

import pytest
from prunepytest.graph import ModuleGraph
from prunepytest.util import chdir

from .conftest import TEST_DATA


def p(v):
    return os.sep.join(v.split("/"))


@pytest.fixture(scope="module")
def g():
    with chdir(TEST_DATA.parent):
        return ModuleGraph(
            source_roots={p("src/prunepytest"): "prunepytest", "tests": "tests"},
            global_prefixes={"prunepytest"},
            local_prefixes={"tests"},
            include_typechecking=False,
        )


@pytest.fixture(scope="module")
def g_everything():
    with chdir(TEST_DATA.parent):
        return ModuleGraph(
            source_roots={p("src/prunepytest"): "prunepytest", "tests": "tests"},
            global_prefixes={"prunepytest"},
            local_prefixes={"tests"},
            external_prefixes={
                "importlib",
                "builtins.__import__",
                "__import__",
                "pytest",
            },
            include_typechecking=True,
        )


def test_file_depends_on(g):
    assert g.file_depends_on(p("src/prunepytest/__init__.py")) == set()
    assert g.file_depends_on(p("src/prunepytest/api.py")) == {"prunepytest"}
    assert g.file_depends_on(p("src/prunepytest/plugin.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.tracker",
        "prunepytest.util",
        "prunepytest.vcs",
        "prunepytest.vcs.detect",
        "prunepytest.vcs.git",
    }
    assert g.file_depends_on(p("src/prunepytest/tracker.py")) == {"prunepytest"}
    assert g.file_depends_on(p("src/prunepytest/util.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
    }
    assert g.file_depends_on(p("src/prunepytest/validator.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.args",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.tracker",
        "prunepytest.util",
    }
    assert g.file_depends_on("prunepytest.plugin") is None
    assert g.file_depends_on(p("tests/prunepytest/test_tracker.py")) == {
        "prunepytest",
        "prunepytest.tracker",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.tracker_helper",
    }
    assert g.file_depends_on(p("tests/prunepytest/test_defaults.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.conftest",
    }


def test_file_depends_on_everything(g_everything):
    g = g_everything
    assert g.file_depends_on(p("src/prunepytest/__init__.py")) == set()
    assert g.file_depends_on(p("src/prunepytest/api.py")) == {
        "prunepytest",
    }
    assert g.file_depends_on(p("src/prunepytest/plugin.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.tracker",
        "prunepytest.util",
        "prunepytest.vcs",
        "prunepytest.vcs.detect",
        "prunepytest.vcs.git",
        "importlib",
        "pytest",
        "__import__",
    }
    assert g.file_depends_on(p("src/prunepytest/tracker.py")) == {
        "prunepytest",
        "importlib",
    }
    assert g.file_depends_on(p("src/prunepytest/util.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
        "importlib",
        "__import__",
    }
    assert g.file_depends_on(p("src/prunepytest/validator.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.args",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.tracker",
        "prunepytest.util",
        "importlib",
        "__import__",
    }
    assert g.file_depends_on("prunepytest.plugin") is None
    assert g.file_depends_on(p("tests/prunepytest/test_tracker.py")) == {
        "prunepytest",
        "prunepytest.tracker",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.tracker_helper",
        "importlib",
        "builtins",
        "builtins.__import__",
        "pytest",
    }
    assert g.file_depends_on(p("tests/prunepytest/test_defaults.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.conftest",
        "__import__",
        "pytest",
    }


def test_module_depends_on(g):
    assert g.module_depends_on("prunepytest") == set()
    assert g.module_depends_on("prunepytest.api") == {"prunepytest"}
    assert g.module_depends_on("prunepytest.plugin") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.tracker",
        "prunepytest.util",
        "prunepytest.vcs",
        "prunepytest.vcs.detect",
        "prunepytest.vcs.git",
    }
    assert g.module_depends_on("prunepytest.tracker") == {"prunepytest"}
    assert g.module_depends_on("prunepytest.util") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
    }
    assert g.module_depends_on("prunepytest.validator") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.args",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.tracker",
        "prunepytest.util",
    }
    assert g.module_depends_on(p("src/prunepytest/plugin.py")) is None
    assert g.module_depends_on("tests.prunepytest.test_tracker", "tests") == {
        "prunepytest",
        "prunepytest.tracker",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.tracker_helper",
    }
    assert g.module_depends_on("tests.prunepytest.test_defaults", "tests") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.conftest",
    }
    assert g.module_depends_on("tests.prunepytest.test_plugin_validate", "tests") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.plugin",
        "prunepytest.util",
        "prunepytest.tracker",
        "prunepytest.vcs",
        "prunepytest.vcs.detect",
        "prunepytest.vcs.git",
        "tests",
        "tests.prunepytest",
    }


def test_module_depends_on_everything(g_everything):
    g = g_everything
    assert g.module_depends_on("prunepytest") == set()
    assert g.module_depends_on("prunepytest.api") == {
        "prunepytest",
    }
    assert g.module_depends_on("prunepytest.plugin") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.tracker",
        "prunepytest.util",
        "prunepytest.vcs",
        "prunepytest.vcs.detect",
        "prunepytest.vcs.git",
        "importlib",
        "__import__",
        "pytest",
    }
    assert g.module_depends_on("prunepytest.tracker") == {
        "prunepytest",
        "importlib",
    }
    assert g.module_depends_on("prunepytest.util") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
        "importlib",
        "__import__",
    }
    assert g.module_depends_on("prunepytest.validator") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.args",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.tracker",
        "prunepytest.util",
        "importlib",
        "__import__",
    }
    assert g.module_depends_on(p("src/prunepytest/plugin.py")) is None
    assert g.module_depends_on("tests.prunepytest.test_tracker", "tests") == {
        "prunepytest",
        "prunepytest.tracker",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.tracker_helper",
        "importlib",
        "builtins",
        "builtins.__import__",
        "pytest",
    }
    assert g.module_depends_on("tests.prunepytest.test_defaults", "tests") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.conftest",
        "__import__",
        "pytest",
    }
    assert g.module_depends_on("tests.prunepytest.test_plugin_validate", "tests") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.plugin",
        "prunepytest.util",
        "prunepytest.tracker",
        "prunepytest.vcs",
        "prunepytest.vcs.detect",
        "prunepytest.vcs.git",
        "tests",
        "tests.prunepytest",
        "importlib",
        "__import__",
        "pytest",
    }


def test_affected_by_files(g):
    assert g.affected_by_files([p("src/prunepytest/plugin.py")]) == {
        p("tests/prunepytest/test_plugin_select.py"),
        p("tests/prunepytest/test_plugin_validate.py"),
    }


def test_affected_by_files_everything(g_everything):
    g = g_everything
    assert g.affected_by_files([p("src/prunepytest/__init__.py")]) == {
        p("src/prunepytest/_prunepytest.pyi"),
        p("src/prunepytest/__main__.py"),
        p("src/prunepytest/api.py"),
        p("src/prunepytest/args.py"),
        p("src/prunepytest/defaults.py"),
        p("src/prunepytest/plugin.py"),
        p("src/prunepytest/graph.py"),
        p("src/prunepytest/tracker.py"),
        p("src/prunepytest/util.py"),
        p("src/prunepytest/validator.py"),
        p("src/prunepytest/vcs/__init__.py"),
        p("src/prunepytest/vcs/detect.py"),
        p("src/prunepytest/vcs/git.py"),
        p("tests/prunepytest/tracker_helper.py"),
        p("tests/prunepytest/test_graph.py"),
        p("tests/prunepytest/test_plugin_select.py"),
        p("tests/prunepytest/test_plugin_validate.py"),
        p("tests/prunepytest/test_tracker.py"),
        p("tests/prunepytest/test_defaults.py"),
        p("tests/prunepytest/test_validator.py"),
    }


def test_affected_by_modules(g):
    assert g.affected_by_modules(["prunepytest.plugin"]) == {
        "tests.prunepytest.test_plugin_select",
        "tests.prunepytest.test_plugin_validate",
    }


def test_affected_by_module_everything(g_everything):
    g = g_everything
    assert g.affected_by_modules(["prunepytest._prunepytest"]) == {
        "prunepytest.__main__",
        "prunepytest.defaults",
        "prunepytest.graph",
        "prunepytest.plugin",
        "prunepytest.util",
        "prunepytest.validator",
        "tests.prunepytest.test_graph",
        "tests.prunepytest.test_plugin_select",
        "tests.prunepytest.test_plugin_validate",
        "tests.prunepytest.test_defaults",
        "tests.prunepytest.test_validator",
    }


def test_local_affected_by_files(g):
    assert g.local_affected_by_files([p("src/prunepytest/plugin.py")]) == {
        "tests": {
            p("tests/prunepytest/test_plugin_select.py"),
            p("tests/prunepytest/test_plugin_validate.py"),
        }
    }


def test_local_affected_by_modules(g):
    assert g.local_affected_by_modules(["prunepytest.plugin"]) == {
        "tests": {
            "tests.prunepytest.test_plugin_select",
            "tests.prunepytest.test_plugin_validate",
        }
    }


def test_dynamic_dependencies_at_leaves_varying_global(g):
    # clone before modification to avoid interfering with other tests
    g = g.clone()

    assert g.module_depends_on("tests.prunepytest.test_tracker", "tests") == {
        "prunepytest",
        "prunepytest.tracker",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.tracker_helper",
    }

    assert "tests.prunepytest.test_tracker" not in g.affected_by_modules(
        ["prunepytest.api"]
    )

    g.add_dynamic_dependencies_at_leaves(
        [
            ("prunepytest.tracker", {"tests": {"prunepytest.api"}}),
        ],
    )

    assert g.module_depends_on("tests.prunepytest.test_tracker", "tests") == {
        "prunepytest",
        "prunepytest.api",
        "prunepytest.tracker",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.tracker_helper",
    }

    assert p("tests/prunepytest/test_tracker.py") in g.affected_by_files(
        [p("src/prunepytest/api.py")]
    )
    assert "tests.prunepytest.test_tracker" in g.affected_by_modules(
        ["prunepytest.api"]
    )


def test_dynamic_dependencies_at_leaves_varying_local(g):
    # clone before modification to avoid interfering with other tests
    g = g.clone()

    assert g.module_depends_on("tests.prunepytest.test_tracker", "tests") == {
        "prunepytest",
        "prunepytest.tracker",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.tracker_helper",
    }
    assert "tests.prunepytest.test_tracker" not in g.affected_by_modules(
        ["tests.prunepytest.tracker_helper"]
    )

    g.add_dynamic_dependencies_at_leaves(
        [
            (
                p("tests/prunepytest/tracker_helper.py"),
                {"tests": {"prunepytest.vcs.git"}},
            ),
        ],
    )

    assert g.module_depends_on("tests.prunepytest.test_tracker", "tests") == {
        "prunepytest",
        "prunepytest.tracker",
        "prunepytest.vcs",
        "prunepytest.vcs.git",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.tracker_helper",
    }

    assert p("tests/prunepytest/test_tracker.py") in g.affected_by_files(
        [p("src/prunepytest/vcs/git.py")]
    )
    assert "tests.prunepytest.test_tracker" in g.affected_by_modules(
        ["prunepytest.vcs.git"]
    )


def test_pyi():
    with chdir(TEST_DATA):
        g = ModuleGraph(
            source_roots={p("pyi"): "pyi"},
            global_prefixes={"pyi"},
            local_prefixes=set(),
            include_typechecking=False,
        )

        assert g.module_depends_on("pyi.foo") == {"pyi", "pyi.bar", "pyi.baz"}
        assert g.module_depends_on("pyi.bar") == {"pyi", "pyi.baz"}
        assert g.module_depends_on("pyi.baz") == {"pyi"}
        assert g.module_depends_on("pyi.qux") == {
            "pyi",
            "pyi.foo",
            "pyi.bar",
            "pyi.baz",
        }

        assert g.file_depends_on(p("pyi/foo.pyi")) == {"pyi", "pyi.bar", "pyi.baz"}
        assert g.file_depends_on(p("pyi/foo.py")) is None
        assert g.file_depends_on(p("pyi/bar.pyi")) == {"pyi", "pyi.baz"}
        assert g.file_depends_on(p("pyi/bar.py")) is None
        assert g.file_depends_on(p("pyi/baz.py")) == {"pyi"}
        assert g.file_depends_on(p("pyi/baz.pyi")) is None
        assert g.file_depends_on(p("pyi/qux.py")) == {
            "pyi",
            "pyi.foo",
            "pyi.bar",
            "pyi.baz",
        }
        assert g.file_depends_on(p("pyi/qux.pyi")) is None

        assert g.affected_by_modules(["pyi.foo"]) == {"pyi.qux"}
        assert g.affected_by_modules(["pyi.bar"]) == {"pyi.foo", "pyi.qux"}
        assert g.affected_by_modules(["pyi.baz"]) == {"pyi.bar", "pyi.foo", "pyi.qux"}
        assert g.affected_by_modules(["pyi.qux"]) == set()

        assert g.affected_by_files([p("pyi/foo.pyi")]) == {p("pyi/qux.py")}
        assert g.affected_by_files([p("pyi/bar.pyi")]) == {
            p("pyi/foo.pyi"),
            p("pyi/qux.py"),
        }
        assert g.affected_by_files([p("pyi/baz.py")]) == {
            p("pyi/bar.pyi"),
            p("pyi/foo.pyi"),
            p("pyi/qux.py"),
        }
        assert g.affected_by_files([p("pyi/baz.pyi")]) == set()
        assert g.affected_by_files([p("pyi/qux.py")]) == set()
        assert g.affected_by_files([p("pyi/qux.pyi")]) == set()
