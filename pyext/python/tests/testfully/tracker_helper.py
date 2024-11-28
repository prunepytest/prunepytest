import io
import sys

from testfully.tracker import Tracker
from typing import AbstractSet, Mapping

class CleanImportTrackerContext:
    """
    Context manager to simplify testing the import tracker

    - cleans up sys.modules around the test case to avoid cross-test contamination
    - starts and stop a fresh Tracker object
    - asserts that tracked imports match expectations
    """
    prefix: str
    tracker: Tracker
    expected_tracked: Mapping[str, AbstractSet[str]]
    with_dynamic : bool

    def __init__(self, prefix, expect_tracked, with_dynamic=False, dynamic_anchors=None) -> None:
        self.prefix = prefix
        self.expected_tracked = expect_tracked
        self.with_dynamic = with_dynamic
        self.dynamic_anchors = dynamic_anchors
        self.tracker = Tracker()

    def __enter__(self) -> 'CleanImportTrackerContext':
        self._cleanup()
        self.tracker.start_tracking({self.prefix},
                                    record_dynamic=self.with_dynamic,
                                    dynamic_anchors=self.dynamic_anchors,
                                    log_file=io.StringIO())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.tracker.stop_tracking()
        details = self.tracker.log_file.getvalue()
        self.tracker.log_file.close()
        self._cleanup()

        if exc_val:
            print(details)
        else:
            try:
                for k, v in self.expected_tracked.items():
                    t = self.tracker.with_dynamic(k) if self.with_dynamic else self.tracker.tracked[k]
                    assert t == v, f"mismatching imports for {k}: expected {v} != actual {t}"
            except BaseException:
                print(details)
                raise

    def _cleanup(self) -> None:
        for m in list(sys.modules):
            if m.startswith(self.prefix):
                del sys.modules[m]
