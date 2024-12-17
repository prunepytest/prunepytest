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
                # track native code as an external prefix since it has no matching .py
                "prunepytest._prunepytest",
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
        "prunepytest.api",
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
        "prunepytest.api",
        "prunepytest.graph",
    }
    assert g.file_depends_on(p("src/prunepytest/validator.py")) == {
        "prunepytest",
        "prunepytest.api",
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
    assert g.file_depends_on(p("tests/prunepytest/test_util.py")) == {
        "prunepytest",
        "prunepytest.api",
        "prunepytest.graph",
        "prunepytest.util",
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
        "prunepytest.graph",
        "importlib",
        "__import__",
    }
    assert g.file_depends_on(p("src/prunepytest/validator.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
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
    assert g.file_depends_on(p("tests/prunepytest/test_util.py")) == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.graph",
        "prunepytest.util",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.conftest",
        "importlib",
        "__import__",
        "pytest",
    }


def test_module_depends_on(g):
    assert g.module_depends_on("prunepytest") == set()
    assert g.module_depends_on("prunepytest.api") == {"prunepytest"}
    assert g.module_depends_on("prunepytest.plugin") == {
        "prunepytest",
        "prunepytest.api",
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
        "prunepytest.api",
        "prunepytest.graph",
    }
    assert g.module_depends_on("prunepytest.validator") == {
        "prunepytest",
        "prunepytest.api",
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
    assert g.module_depends_on("tests.prunepytest.test_util", "tests") == {
        "prunepytest",
        "prunepytest.api",
        "prunepytest.graph",
        "prunepytest.util",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.conftest",
    }
    assert g.module_depends_on("tests.prunepytest.test_plugin_validate", "tests") == {
        "prunepytest",
        "prunepytest.api",
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
        "prunepytest.graph",
        "importlib",
        "__import__",
    }
    assert g.module_depends_on("prunepytest.validator") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
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
    assert g.module_depends_on("tests.prunepytest.test_util", "tests") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
        "prunepytest.graph",
        "prunepytest.util",
        "tests",
        "tests.prunepytest",
        "tests.prunepytest.conftest",
        "importlib",
        "__import__",
        "pytest",
    }
    assert g.module_depends_on("tests.prunepytest.test_plugin_validate", "tests") == {
        "prunepytest",
        "prunepytest._prunepytest",
        "prunepytest.api",
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
        p("src/prunepytest/api.py"),
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
        p("tests/prunepytest/test_util.py"),
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
        "prunepytest.graph",
        "prunepytest.plugin",
        "prunepytest.util",
        "prunepytest.validator",
        "tests.prunepytest.test_graph",
        "tests.prunepytest.test_plugin_select",
        "tests.prunepytest.test_plugin_validate",
        "tests.prunepytest.test_util",
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
            ("tests/prunepytest/tracker_helper.py", {"tests": {"prunepytest.vcs.git"}}),
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
