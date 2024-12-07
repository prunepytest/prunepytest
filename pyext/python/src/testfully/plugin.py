"""
pytest plugin
"""

import warnings

import pathlib
import pytest
import subprocess

from typing import Any, AbstractSet, Optional, List

from _pytest._code import Traceback
from _pytest.config import ExitCode
from _pytest.reports import TestReport
from _pytest.runner import CallInfo
from testfully.tracker import IGNORED_FRAMES
from typing_extensions import Generator

from . import ModuleGraph
from .api import PluginHook, ZeroConfHook
from .util import load_import_graph, load_hook, hook_zeroconf
from .tracker import Tracker
from .vcs.detect import detect_vcs


# detect xdist and adjust behavior accordingly
try:
    from xdist import is_xdist_controller, is_xdist_worker  # type: ignore[import-not-found]
except ImportError:
    is_xdist_controller = is_xdist_worker = lambda session: False


class UnexpectedImportException(Exception):
    def __init__(self, msg: str):
        super().__init__(msg)


def raise_(e: BaseException) -> None:
    raise e


def pytest_addoption(parser: Any, pluginmanager: Any) -> None:
    group = parser.getgroup(
        "automatically select tests affected by changes (testfully)"
    )

    group.addoption(
        "--testfully",
        action="store_true",
        dest="testfully",
        help=("Select tests affected by changes (based on import graph)."),
    )

    group.addoption(
        "--tf-noselect",
        action="store_true",
        dest="testfully_noselect",
        help=("Keep default test selection, instead of pruning irrelevant tests"),
    )

    group.addoption(
        "--tf-novalidate",
        action="store_true",
        dest="testfully_novalidate",
        help=("Skip validation of dynamic imports"),
    )

    group.addoption(
        "--tf-warnonly",
        action="store_true",
        dest="testfully_warnonly",
        help=("Only warn instead of failing upon unexpected imports"),
    )

    group.addoption(
        "--tf-hook",
        action="store",
        type=str,
        dest="testfully_hook",
        help=("File containing an implementation of testfully.api.PluginHook"),
    )

    group.addoption(
        "--tf-graph-root",
        action="store",
        type=str,
        dest="testfully_graph_root",
        help=("Root path, to which all paths in the import graph are relative"),
    )

    group.addoption(
        "--tf-graph",
        action="store",
        type=str,
        dest="testfully_graph",
        default=".testfully.bin",
        help=("File in which the import graph is stored"),
    )


def pytest_configure(config: Any) -> None:
    opt = config.option
    if not opt.testfully:
        return

    # Skip this plugin entirely when only doing collection.
    if config.getvalue("collectonly"):
        return

    # old versions of pluggy do not have force_exception...
    import pluggy  # type: ignore[import-untyped]

    if pluggy.__version__ < "1.2":
        raise ValueError("testfully requires pluggy>=1.2")

    if opt.testfully_hook:
        hook = load_hook(config.rootpath, opt.testfully_hook, PluginHook)  # type: ignore[type-abstract]
    else:
        hook = hook_zeroconf(config.rootpath, ZeroConfHook)

    vcs = detect_vcs()

    if opt.testfully_graph_root:
        rel_root = config.rootpath.relative_to(opt.testfully_graph_root)
    elif vcs:
        # the import graph is assumed to be full of repo-relative path
        # so we need to adjust in case of running tests in a subdir
        try:
            repo_root = vcs.repo_root()
            rel_root = config.rootpath.relative_to(repo_root)
        except subprocess.CalledProcessError:
            rel_root = None

    # TODO: chdir to make sure the import graph is for the whole repo?
    # TODO: coordinate with pytest-xdist, if used, to avoid redundant work here...
    # e.g. use a temporary file to serialize graph if no explicit graph used...
    graph = load_import_graph(hook, opt.testfully_graph)

    if not opt.testfully_novalidate:
        config.pluginmanager.register(
            TestfullyValidate(hook, graph, rel_root),
            "TestfullyValidate",
        )

    if not opt.testfully_noselect:
        if vcs is None:
            raise ValueError("unsupported VCS for test selection...")

        # TODO: accept args to specify target and base commits
        # TODO: extract derivation of affected set to helper function

        if vcs.is_repo_clean():
            print("deriving test set for changes in last commit")
            modified = vcs.modified_files()
        else:
            print("deriving test set for uncommitted changes")
            modified = vcs.dirty_files()

        print(f"modified: {modified}")

        affected = graph.affected_by_files(modified)
        print(f"affected: {affected}")

        config.pluginmanager.register(
            TestfullySelect(affected | set(modified)),
            "TestfullySelect",
        )


class TestfullyValidate:
    def __init__(
        self, hook: PluginHook, graph: ModuleGraph, rel_root: pathlib.Path
    ) -> None:
        self.hook = hook
        self.graph = graph
        self.rel_root = rel_root
        self.tracker = Tracker()
        self.tracker.start_tracking(
            hook.global_namespaces() | hook.local_namespaces(),
            patches=hook.import_patches(),
            record_dynamic=True,
            dynamic_anchors=hook.dynamic_anchors(),
            dynamic_ignores=hook.dynamic_ignores(),
            # TODO: override from pytest config?
            log_file=hook.tracker_log(),
        )

        # pytest-xdist is a pain to deal with:
        # the controller and each worker get an independent instance of the plugin
        # then the controller mirrors all the hook invocations of *every* worker,
        # interleaved in arbitrary order. To avoid creating nonsensical internal
        # state, we need to skip some hook processing on the controller
        # Unfortunately, the only reliable way to determine worker/controller context,
        # is by checking the Session object, which is created after the hook object,
        # and not passed to every hook function, so we have to detect context on the
        # first hook invocation, and refer to it in subsequent invocations.
        self.is_controller = False

        # we track imports at module granularity, but we have to run validation at
        # test item granularity to be able to accurately attach warnings and errors
        self.current_file: Optional[str] = None
        self.expected_imports: Optional[AbstractSet[str]] = None

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)  # type: ignore
    def pytest_sessionstart(
        self, session: pytest.Session
    ) -> Generator[Any, None, None]:
        if is_xdist_controller(session):
            self.is_controller = True

        return (yield)

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
            i = 0
            # remove the tail of the traceback, starting at the first frame that lands
            # in the tracker, or importlib
            while (
                i + 1 < len(tb)
                and tb[i + 1]._rawentry.tb_frame.f_code.co_filename
                not in IGNORED_FRAMES
            ):
                i += 1
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
        # only performa validation on workers when running with xdist...
        if self.is_controller:
            return (yield)

        f = item.location[0]

        # TODO: might need further path adjustment?
        graph_path = str(self.rel_root / f) if self.rel_root else f
        import_path = f[:-3].replace("/", ".")

        def import_callback(name: str) -> None:
            if self.expected_imports and name not in self.expected_imports:
                if item.session.config.option.testfully_warnonly:
                    # TODO: stack?
                    warnings.warn(f"unexpected import {name}")
                else:
                    raise UnexpectedImportException(f"unexpected import {name}")

        # NB: we're registering an import callback so we can immediately fail the
        # test with a clear traceback on the first unexpected import
        self.tracker.enter_context(import_path, import_callback)

        before = self.tracker.with_dynamic(import_path)

        if graph_path != self.current_file:
            self.current_file = graph_path
            self.expected_imports = self.graph.file_depends_on(graph_path) or set()

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
        unexpected = caused_by_test - expected
        if unexpected:
            _report_unexpected(item, unexpected)

        return outcome


def _report_unexpected(item: pytest.Item, unexpected: AbstractSet[str]) -> None:
    if item.session.config.option.testfully_warnonly:
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


class TestfullySelect:
    def __init__(self, affected: AbstractSet[str]) -> None:
        self.affected = affected

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_collection_modifyitems(
        self, session: pytest.Session, config: pytest.Config, items: List[pytest.Item]
    ) -> None:
        n = len(items)
        skipped = []

        # loop from the end to easily remove items as we go
        i = len(items) - 1
        while i >= 0:
            item = items[i]
            keep = item.location[0] in self.affected
            if not keep:
                skipped.append(item)
                del items[i]
            i -= 1

        session.ihook.pytest_deselected(items=skipped)

        print(f"skipped: {len(skipped)}/{n}")

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_sessionfinish(
        self, session: pytest.Session, exitstatus: ExitCode
    ) -> None:
        if exitstatus == ExitCode.NO_TESTS_COLLECTED:
            session.exitstatus = ExitCode.OK
