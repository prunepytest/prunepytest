# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
pytest plugin for prune-py-test

includes two parts:
 - a test case selector, based on import graph and modified files
 - a validator to flag unexpected imports, providing confidence that test (de)selection is sound
"""

import os
import warnings

import pathlib
import pytest

from typing import Any, AbstractSet, Optional, List, Generator, Tuple

from _pytest._code import Traceback
from _pytest.config import ExitCode
from _pytest.reports import TestReport
from _pytest.runner import CallInfo
from _pytest.tmpdir import TempPathFactory

from . import ModuleGraph
from .api import PluginHook, ZeroConfHook
from .util import chdir, load_import_graph, load_hook, hook_zeroconf
from .tracker import Tracker, relevant_frame_index, warning_skip_level
from .vcs.detect import detect_vcs


# detect xdist and adjust behavior accordingly
try:
    from xdist import is_xdist_controller  # type: ignore[import-not-found]

    has_xdist = True
except ImportError:
    has_xdist = False

    def is_xdist_controller(session: pytest.Session) -> bool:
        return False


class UnexpectedImportException(AssertionError):
    def __init__(self, msg: str):
        super().__init__(msg)


def raise_(e: BaseException) -> None:
    raise e


def pytest_addoption(parser: Any, pluginmanager: Any) -> None:
    group = parser.getgroup(
        "automatically select tests affected by changes (prune-py-test)"
    )

    group.addoption(
        "--prune",
        action="store_true",
        dest="prune",
        help=("Enable prune-py-test plugin"),
    )

    group.addoption(
        "--prune-no-validate",
        action="store_true",
        dest="prune_novalidate",
        help=(
            "Skip validation that each tests only imports modules predicted by the import graph"
        ),
    )

    group.addoption(
        "--prune-no-select",
        action="store_true",
        dest="prune_noselect",
        help=("Keep default test selection, disable pruning irrelevant tests"),
    )

    group.addoption(
        "--prune-modified-files",
        action="store",
        type=str,
        dest="prune_modified_files",
        help=(
            "Comma-separated list of modified files to use as basis for test selection."
            "The default behavior is to use data from the last git (or other supported VCS)"
            "commit, and uncommitted changes."
            "If specified, takes precedence over --base-commit"
        ),
    )

    group.addoption(
        "--prune-base-commit",
        action="store",
        type=str,
        dest="prune_base_commit",
        help=("Base commit id to use when computing affected files."),
    )

    group.addoption(
        "--prune-no-fail",
        action="store_true",
        dest="prune_nofail",
        help=("Only warn, instead of failing tests that trigger unexpected imports"),
    )

    group.addoption(
        "--prune-hook",
        action="store",
        type=str,
        dest="prune_hook",
        help=("File containing an implementation of prunepytest.api.PluginHook"),
    )

    group.addoption(
        "--prune-graph-root",
        action="store",
        type=str,
        dest="prune_graph_root",
        help=("Root path, to which all paths in the import graph are relative"),
    )

    group.addoption(
        "--prune-graph",
        action="store",
        type=str,
        dest="prune_graph",
        help=(
            "Path to an existing serialized import graph"
            "to be used, instead of computing a fresh one."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    opt = config.option
    if not opt.prune:
        return

    # Skip this plugin entirely when only doing collection.
    if config.getvalue("collectonly"):
        return

    # old versions of pluggy do not have force_exception...
    import pluggy  # type: ignore[import-untyped]

    if pluggy.__version__ < "1.2":
        raise ValueError("prune-py-test requires pluggy>=1.2")

    if opt.prune_hook:
        hook = load_hook(config.rootpath, opt.prune_hook, PluginHook)  # type: ignore[type-abstract]
        hook.setup()
    else:
        hook = hook_zeroconf(config.rootpath, ZeroConfHook)

    vcs = detect_vcs()

    graph_root = opt.prune_graph_root or (
        vcs.repo_root() if vcs else str(config.rootpath)
    )
    rel_root = config.rootpath.relative_to(graph_root)

    graph_path = opt.prune_graph
    if graph_path and not os.path.isfile(graph_path):
        graph_path = None

    if has_xdist:
        # when running under xdist we want to avoid redundant work so we save the graph
        # computed by the controller in a temporary folder shared with all workers
        # with name that is based on the test run id so every worker can easily find it
        if not graph_path:
            tmpdir: pathlib.Path = TempPathFactory.from_config(
                config, _ispytest=True
            ).getbasetemp()
            graph_path = str(tmpdir / "prune-graph.bin")

        # use xdist hooks to propagate the path to all workers
        class XdistConfig:
            @pytest.hookimpl()  # type: ignore
            def pytest_configure_node(self, node: Any) -> None:
                # print(f"configure node {node.workerinput['workerid']}: graph_path={graph_path}")
                node.workerinput["graph_path"] = graph_path

        config.pluginmanager.register(XdistConfig(), "PruneXdistConfig")

    graph = GraphLoader(config, hook, graph_path, graph_root)

    if not opt.prune_novalidate:
        config.pluginmanager.register(
            PruneValidator(hook, graph, rel_root),
            "PruneValidator",
        )

    if not opt.prune_noselect:
        if opt.prune_modified_files is not None:
            modified = opt.prune_modified_files.split(",")
        elif vcs:
            modified = (
                vcs.modified_files(base_commit=opt.prune_base_commit)
                + vcs.dirty_files()
            )
        else:
            raise ValueError("unsupported VCS for test selection...")

        print(f"modified: {modified}")

        config.pluginmanager.register(
            PruneSelector(hook, graph, set(modified)),
            "PruneSelector",
        )


def actual_test_file(item: pytest.Item) -> Tuple[str, Optional[str]]:
    """
    Given a pytest Item, return the path of the test file it comes from

    This is usually straightforwardly obtained from item.location[0], but
    sometimes that location does not point to a covered Python file.

    In that case, we perform a best-effort handling of data-driven tests,
    by walking up the Item tree, and looking for a parent whose path is
    a real Python file. If no such file can be found, the test item will
    be treated safely:

     - it is never be deselected based on import graph/modified files
     - import validation is skipped, since we cannot infer a reasonable
       set of imports for that test item, and we want to avoid spurious
       validation errors
    """
    f = item.location[0]
    if not f.endswith(".py"):
        p = item.parent
        while p:
            if p.name.endswith(".py") and os.path.isfile(p.path):
                rel = p.path.relative_to(item.config.rootpath)
                # print(f"mapped {f} -> {rel} {p.path}", file=sys.stderr)
                return str(rel), f
            p = p.parent
    return f, None


class GraphLoader:
    """
    Helper class to abstract away the loading of the import graph, and deal
    with some of the intricacies of interfacing with pytest-xdist
    """

    def __init__(
        self, config: pytest.Config, hook: PluginHook, graph_path: str, graph_root: str
    ) -> None:
        self.config = config
        self.hook = hook
        self.graph_path = graph_path
        self.graph_root = graph_root
        self.graph: Optional[ModuleGraph] = None

    def get(self, session: pytest.Session) -> ModuleGraph:
        if not self.graph:
            self.graph = self.load(session)
        return self.graph

    def load(self, session: pytest.Session) -> ModuleGraph:
        if hasattr(session.config, "workerinput"):
            graph_path = session.config.workerinput["graph_path"]
            # print(f"worker loading graph from {graph_path}")
            graph = ModuleGraph.from_file(graph_path)
        else:
            load_path = (
                self.graph_path
                if self.graph_path and os.path.isfile(self.graph_path)
                else None
            )

            with chdir(self.graph_root):
                graph = load_import_graph(self.hook, load_path)

            if is_xdist_controller(session) and not load_path:
                print(f"saving import graph to {self.graph_path}")
                graph.to_file(self.graph_path)

        return graph


class PruneValidator:
    """
    pytest hooks to validate that each test case only imports a subset of the modules
    that the file it is part of is expected to depend on

    When detecting an unexpected import, an error (or warning, depending on config) will
    be reported
    """

    def __init__(
        self, hook: PluginHook, graph: GraphLoader, rel_root: pathlib.Path
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

        self.always_run = hook.always_run()

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)  # type: ignore
    def pytest_sessionstart(
        self, session: pytest.Session
    ) -> Generator[Any, None, None]:
        if is_xdist_controller(session):
            self.is_controller = True
            # ensure the import graph is computed before the workers need it
            self.graph.get(session)

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

        # print(f"validated runtest: {f} [ {item} ]", file=sys.stderr)

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
            print(self.tracker.dynamic_users.get(import_path))
            print(self.tracker.dynamic_imports)
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


class PruneSelector:
    """
    pytest hooks to deselect test cases based on import graph and modified files
    """

    def __init__(
        self, hook: PluginHook, graph: GraphLoader, modified: AbstractSet[str]
    ) -> None:
        self.hook = hook
        self.graph = graph
        self.modified = modified

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_collection_modifyitems(
        self, session: pytest.Session, config: pytest.Config, items: List[pytest.Item]
    ) -> None:
        n = len(items)
        skipped = []

        g = self.graph.get(session)
        affected = g.affected_by_files(self.modified) | self.modified
        # print(f"affected: {affected}", file=sys.stderr)

        covered_files = {}
        always_run = self.hook.always_run()

        # loop from the end to easily remove items as we go
        i = len(items) - 1
        while i >= 0:
            item = items[i]
            file, data = actual_test_file(item)

            if file not in covered_files:
                covered_files[file] = g.file_depends_on(file) is not None

            # keep the test item if any of the following holds:
            # 1. python test file is not covered by the import graph
            # 2. python test file is affected by some modified file(s) according to the import graph
            # 3. data-driven test, and data file was modified
            # 4. file / test case marked as "always_run" by hook
            #
            # NB: at a later point, 3. could be extended by allowing explicit tagging of non-code
            # dependencies with some custom annotation (via comments collected by ModuleGraph, or
            # import-time hook being triggered a test collection time?)
            keep = (
                not covered_files[file]
                or (file in affected)
                or (data and data in self.modified)
                or (file in always_run)
                or (item.name in always_run)
            )
            if not keep:
                skipped.append(item)
                del items[i]
            i -= 1

        session.ihook.pytest_deselected(items=skipped)

        if config.option.verbose > 1:
            print(f"skipped: {len(skipped)}/{n}")

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_sessionfinish(
        self, session: pytest.Session, exitstatus: ExitCode
    ) -> None:
        if exitstatus == ExitCode.NO_TESTS_COLLECTED:
            session.exitstatus = ExitCode.OK
