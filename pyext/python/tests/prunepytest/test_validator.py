# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

import os.path
import tempfile

import pytest

from prunepytest.util import chdir
from prunepytest.validator import validate

from .conftest import TEST_DATA


def test_validator_default_from_pyext_python() -> None:
    python_dir = TEST_DATA.parent

    with chdir(python_dir):
        n_err, n_missing = validate(None)

        assert n_err == 0
        assert n_missing == 0


def test_validator_default_from_pyext() -> None:
    pyext_dir = TEST_DATA.parent.parent

    with chdir(pyext_dir):
        n_err, n_missing = validate(None)

        assert n_err == 0
        assert n_missing == 0


def test_validator_default_from_repo_root() -> None:
    root_dir = TEST_DATA.parent.parent.parent

    with chdir(root_dir):
        n_err, n_missing = validate(None)

        assert n_err == 0
        assert n_missing == 0


def test_validator_default_with_graph() -> None:
    python_dir = TEST_DATA.parent

    with chdir(python_dir), tempfile.TemporaryDirectory() as tmpdir:
        graph_path = os.path.join(tmpdir, "graph.bin")
        n_err, n_missing = validate(None, graph_path)

        assert n_err == 0
        assert n_missing == 0

        n_err, n_missing = validate(None, graph_path)

        assert n_err == 0
        assert n_missing == 0


DEFAULT_HOOK_PY = """
from prunepytest.api import DefaultHook

def foo():
    pass

class NotAHook:
    pass

class TestHook(DefaultHook):
    pass
"""


def test_validator_with_custom_default_hook() -> None:
    python_dir = TEST_DATA.parent

    with chdir(python_dir), tempfile.TemporaryDirectory() as tmpdir:
        hook_path = os.path.join(tmpdir, "hook.py")
        with open(hook_path, "w") as f:
            f.write(DEFAULT_HOOK_PY)

        n_err, n_missing = validate(hook_path)
        assert n_err == 0
        assert n_missing == 0


HOOK_PY = """
from prunepytest.api import ValidatorHook

class TestHook(ValidatorHook):
    def global_namespaces(self):
        return {"prunepytest"}

    def local_namespaces(self):
        return {"tests"}

    def source_roots(self):
        return {"src/prunepytest": "prunepytest", "tests": "tests"}

    def test_folders(self):
        return {"tests": "tests"}
"""


def test_validator_with_custom_hook() -> None:
    python_dir = TEST_DATA.parent

    with chdir(python_dir), tempfile.TemporaryDirectory() as tmpdir:
        hook_path = os.path.join(tmpdir, "hook.py")
        with open(hook_path, "w") as f:
            f.write(HOOK_PY)

        n_err, n_missing = validate(hook_path)
        assert n_err == 0
        assert n_missing == 0


INVALID_HOOK_PY = """
from prunepytest.api import ValidatorHook

class StillAbstract(ValidatorHook):
    pass

"""


def test_validator_invalid_hook() -> None:
    python_dir = TEST_DATA.parent

    with chdir(python_dir), tempfile.TemporaryDirectory() as tmpdir:
        hook_path = os.path.join(tmpdir, "hook.py")
        with open(hook_path, "w") as f:
            f.write(INVALID_HOOK_PY)

        with pytest.raises(TypeError):
            validate(hook_path)


MISSING_HOOK_PY = """
from prunepytest.api import ValidatorHook

"""


def test_validator_missing_hook() -> None:
    python_dir = TEST_DATA.parent

    with chdir(python_dir), tempfile.TemporaryDirectory() as tmpdir:
        hook_path = os.path.join(tmpdir, "hook.py")
        with open(hook_path, "w") as f:
            f.write(MISSING_HOOK_PY)

        with pytest.raises(ValueError):
            validate(hook_path)
