import os
import pathlib

import pytest
import sys

from testfully.tracker import Tracker


class CleanImports:
    prefix: str

    def __init__(self, prefix):
        self.prefix = prefix

    def __enter__(self):
        self.cleanup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

    def cleanup(self):
        for m in list(sys.modules):
            if m.startswith(self.prefix):
                del sys.modules[m]

def setup_module():
    test_data_path = str(pathlib.PurePath(__file__).parents[2] / 'test-data')
    if test_data_path not in sys.path:
        sys.path.insert(0, test_data_path)


class TestTracker:
    def test_import(self):
        with CleanImports('foo'):
            t = Tracker()
            t.start_tracking({'foo'})
            assert "foo.foo.qux" not in t.tracked
            import foo.foo.qux
            t.stop_tracking()
            assert t.tracked["foo"] == set()
            assert t.tracked["foo.foo"] == {'foo'}
            assert t.tracked["foo.foo.qux"] == {'foo', 'foo.foo'}

    def test_import_from_module(self):
        with CleanImports('foo'):
            t = Tracker()
            t.start_tracking({'foo'})
            assert "foo.foo.qux" not in t.tracked
            from foo.foo import qux
            t.stop_tracking()
            assert t.tracked["foo"] == set()
            assert t.tracked["foo.foo"] == {'foo'}
            assert t.tracked["foo.foo.qux"] == {'foo', 'foo.foo'}

    def test_import_from_item(self):
        with CleanImports('foo'):
            t = Tracker()
            t.start_tracking({'foo'})
            assert "foo.foo.qux" not in t.tracked
            from foo.foo.qux import Qux
            t.stop_tracking()
            assert t.tracked["foo"] == set()
            assert t.tracked["foo.foo"] == {'foo'}
            assert t.tracked["foo.foo.qux"] == {'foo', 'foo.foo'}

    def test_builtin_import(self):
        with CleanImports('foo'):
            t = Tracker()
            t.start_tracking({'foo'})
            assert "foo.foo.qux" not in t.tracked
            __import__('foo.foo.qux')
            t.stop_tracking()
            assert t.tracked["foo"] == set()
            assert t.tracked["foo.foo"] == {'foo'}
            assert t.tracked["foo.foo.qux"] == {'foo', 'foo.foo'}

    def test_importlib_import(self):
        with CleanImports('foo'):
            t = Tracker()
            t.start_tracking({'foo'})
            assert "foo.foo.qux" not in t.tracked
            from importlib import __import__
            __import__('foo.foo.qux')
            t.stop_tracking()
            assert t.tracked["foo"] == set()
            assert t.tracked["foo.foo"] == {'foo'}
            assert t.tracked["foo.foo.qux"] == {'foo', 'foo.foo'}

    def test_importlib_import_module(self):
        with CleanImports('foo'):
            t = Tracker()
            t.start_tracking({'foo'})
            assert "foo.foo.qux" not in t.tracked
            from importlib import import_module
            import_module('foo.foo.qux')
            t.stop_tracking()
            assert t.tracked["foo"] == set()
            assert t.tracked["foo.foo"] == {'foo'}
            assert t.tracked["foo.foo.qux"] == {'foo', 'foo.foo'}
