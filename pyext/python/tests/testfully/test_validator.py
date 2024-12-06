import contextlib

from testfully.validator import validate


from .conftest import TEST_DATA


def test_validator_zeroconf_from_pyext_python() -> None:
    python_dir = TEST_DATA.parent

    with contextlib.chdir(python_dir):
        n_err, n_missing = validate(None)

        assert n_err == 0
        assert n_missing == 0


def test_validator_zeroconf_from_pyext() -> None:
    pyext_dir = TEST_DATA.parent.parent

    with contextlib.chdir(pyext_dir):
        n_err, n_missing = validate(None)

        assert n_err == 0
        assert n_missing == 0


def test_validator_zeroconf_from_repo_root() -> None:
    root_dir = TEST_DATA.parent.parent.parent

    with contextlib.chdir(root_dir):
        n_err, n_missing = validate(None)

        assert n_err == 0
        assert n_missing == 0
