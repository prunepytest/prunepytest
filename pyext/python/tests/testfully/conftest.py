import os
import pathlib
import sys
from contextlib import contextmanager

import pytest


TEST_DATA = pathlib.PurePath(__file__).parents[2] / "test-data"


@contextmanager
def chdir(d: str):
    prev = os.getcwd()
    os.chdir(d)
    try:
        yield None
    finally:
        os.chdir(prev)


@pytest.fixture(scope="session", autouse=True)
def setup():
    # add the test-data folder to the module search path so we can import our test cases
    test_data_path = str(TEST_DATA)
    if test_data_path not in sys.path:
        sys.path.insert(0, test_data_path)
