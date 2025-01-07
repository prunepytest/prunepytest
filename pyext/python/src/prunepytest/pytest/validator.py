# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import os
import pathlib
import warnings

import pytest

from _pytest._code import Traceback
from _pytest.reports import TestReport
from _pytest.runner import CallInfo

from typing import Any, AbstractSet, Generator, Optional

from ..api import PluginHook
from ..tracker import Tracker, relevant_frame_index, warning_skip_level
from .util import GraphLoader, _XdistHelper, actual_test_file


class UnexpectedImportException(AssertionError):
    def __init__(self, msg: str):
        super().__init__(msg)


def raise_(e: BaseException) -> None:
    raise e


class PruneValidator(_XdistHelper):
    """
    pytest hooks to validate that each test case only imports a subset of the modules
    that the file it is part of is expected to depend on

    When detecting an unexpected import, an error (or warning, depending on config) will
    be reported
    """

    def __init__(
        self, hook: PluginHook, graph: GraphLoader, rel_root: pathlib.Path
    ) -> None:
        super().__init__(graph)
        self.hook = hook
        self.rel_root = rel_root
        self.tracker = Tracker()
        self.tracker.start_tracking(
            hook.global_namespaces() | hook.local_namespaces(),
            patches=hook.import_patches(),
            record_dynamic=True,
            implicit_anchor_aggregation=hook.implicit_anchor_aggregation(),
            dynamic_anchors=hook.dynamic_anchors(),
            dynamic_ignores=hook.dynamic_ignores(),
            # TODO: override from pytest config?
            log_file=hook.tracker_log(),
        )

        # we track imports at module granularity, but we have to run validation at
        # test item granularity to be able to accurately attach warnings and errors
        self.current_file: Optional[str] = None
        self.expected_imports: Optional[AbstractSet[str]] = None
        self.always_run = hook.always_run()

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)  # type: ignore
    def pytest_sessionfinish(
        self, session: pytest.Session
    ) -> Generator[Any, None, None]:
        self.tracker.stop_tracking()

        return (yield)

    @pytest.hookimpl()  # type: ignore
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[None]
    ) -> pytest.TestReport:
        # clean up the traceback for our custom validation exception
        if call.excinfo and call.excinfo.type is UnexpectedImportException:
            tb = call.excinfo.traceback
            # remove the tail of the traceback, starting at the first frame that lands
            # in the tracker, or importlib
            i = relevant_frame_index(tb[0]._rawentry)
            # to properly remove the top of the stack, we need to both
            #  1. shrink the high-level vector
            #  2. sever the link in the underlying low-level linked list of stack frames
            if i < len(tb):
                tb[i]._rawentry.tb_next = None
                call.excinfo.traceback = Traceback(tb[: i + 1])

        # NB: must clean up traceback before creating the report, or it'll keep the old stack trace
        out = TestReport.from_item_and_call(item, call)
        return out

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)  # type: ignore
    def pytest_runtest_protocol(
        self, item: pytest.Item, nextitem: pytest.Item
    ) -> Generator[Any, None, None]:
        #  when running with xdist, skip validation on controller
        if self.is_controller:
            return (yield)

        f, _ = actual_test_file(item)
        # make absolute paths relative to pytest root path
        if os.path.isabs(f):
            rp = str(item.config.rootpath)
            assert f.startswith(rp)
            f = f[len(rp) + 1 :]

        # TODO: might need further path adjustment?
        graph_path = str(self.rel_root / f) if self.rel_root else f
        new_file = graph_path != self.current_file

        if new_file:
            self.current_file = graph_path
            self.expected_imports = self.graph.get(item.session).file_depends_on(
                graph_path
            )

        if (
            # unhandled data-driven test case
            #  - will never be deselected
            #  - validation errors would be spurious as we have no graph coverage...
            not f.endswith(".py")
            or self.expected_imports is None
            # explicitly requested to always run, presumably because of complex dynamic
            # imports that are not worth encoding into the import graph
            or f in self.always_run
            or (f + ":" + item.name.partition("[")[0]) in self.always_run
        ):
            # => skip validation altogether
            if item.session.config.option.verbose > 1:
                print(f"unhandled test case: {f} [ {item} ]")
            return (yield)

        import_path = f[:-3].replace("/", ".")

        # avoid spurious validation errors when using multiprocessing
        self.expected_imports |= {import_path}

        if item.session.config.option.verbose > 1:
            print(f"validated runtest: {f} [ {item} ]")  # , file=sys.stderr)

        # keep track of warnings emitted by the import callback, to avoid double-reporting
        warnings_emitted = set()

        def import_callback(name: str) -> None:
            if not self.expected_imports or name not in self.expected_imports:
                if item.session.config.option.prune_nofail:
                    # stack munging: we want the warning to point to the unexpected import location
                    skip = warning_skip_level()

                    warnings.warn(f"unexpected import {name}", stacklevel=skip)
                    warnings_emitted.add(name)
                else:
                    raise UnexpectedImportException(f"unexpected import {name}")

        # NB: we're registering an import callback so we can immediately fail the
        # test with a clear traceback on the first unexpected import
        self.tracker.enter_context(import_path, import_callback)

        before = self.tracker.with_dynamic(import_path)

        if new_file:
            # sanity check: make sure the import graph covers everything that was
            # imported when loading the test file.
            # We only do that for the first test item in each file
            # NB: might be triggered multiple times with xdist, and that's OK
            unexpected = before - self.expected_imports
            if unexpected:
                _report_unexpected(item, unexpected)

        expected = self.expected_imports or set()

        outcome = yield

        self.tracker.exit_context(import_path)

        after = self.tracker.with_dynamic(import_path)

        # sanity check: did we track any imports that somehow bypassed the callback?
        caused_by_test = after - before
        # NB: for warning-only mode, make sure we avoid double reporting
        unexpected = caused_by_test - expected - warnings_emitted
        if unexpected:
            # TODO: detail where the dynamic imports are coming from
            # print(self.tracker.dynamic_users.get(import_path))
            # print(self.tracker.dynamic_imports)
            _report_unexpected(item, unexpected)

        return outcome


def _report_unexpected(item: pytest.Item, unexpected: AbstractSet[str]) -> None:
    if item.session.config.option.prune_nofail:
        f = item.location[0]
        item.session.ihook.pytest_warning_recorded.call_historic(
            kwargs=dict(
                warning_message=warnings.WarningMessage(
                    f"{len(unexpected)} unexpected imports: {unexpected}",
                    Warning,
                    f,
                    0,
                ),
                when="runtest",
                nodeid=f,
                location=(f, 0, "<module>"),
            )
        )
    else:
        report = TestReport.from_item_and_call(
            item=item,
            call=CallInfo.from_call(
                func=lambda: raise_(
                    ImportError(f"{len(unexpected)} unexpected imports: {unexpected}")
                ),
                when="teardown",
            ),
        )
        item.ihook.pytest_runtest_logreport(report=report)
