import pathlib
import sys

import pytest


@pytest.fixture(scope="session", autouse=True)
def setup():
    # add the test-data folder to the module search path so we can import our test cases
    test_data_path = str(pathlib.PurePath(__file__).parents[2] / "test-data")
    if test_data_path not in sys.path:
        sys.path.insert(0, test_data_path)
