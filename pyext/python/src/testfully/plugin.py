"""
pytest plugin
"""

from warnings import WarningMessage

import pathlib
import pytest
import subprocess

from typing import Any, Set

from . import ModuleGraph
from .api import PluginHook, ZeroConfHook
from .util import load_import_graph, load_hook, hook_zeroconf
from .tracker import Tracker


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
        "--testfully-noselect",
        action="store_true",
        dest="testfully_noselect",
        help=("Keep default test selection, instead of pruning irrelevant tests"),
    )

    group.addoption(
        "--testfully-novalidate",
        action="store_true",
        dest="testfully_novalidate",
        help=("Skip validation of dynamic imports"),
    )

    group.addoption(
        "--testfully-warnonly",
        action="store_true",
        dest="testfully_warnonly",
        help=("Only warn instead of failing upon unexpected imports"),
    )

    group.addoption(
        "--testfully-hook",
        action="store",
        type=str,
        dest="testfully_hook",
        default="testfully-hook.py",
        help=("File in which the import graph is stored"),
    )

    group.addoption(
        "--testfully-graph-root",
        action="store",
        type=str,
        dest="testfully_graph_root",
        help=("File in which the import graph is stored"),
    )

    group.addoption(
        "--testfully-graph",
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

    # old versions of pluggy do not have force_exception...
    import pluggy  # type: ignore[import-untyped]

    if pluggy.__version__ < "1.2":
        raise ValueError("testfully requires pluggy>=1.2")

    if opt.testfully_hook:
        hook = load_hook(config.rootpath, opt.testfully_hook, PluginHook)  # type: ignore[type-abstract]
    else:
        hook = hook_zeroconf(config.rootpath, ZeroConfHook)

    if opt.testfully_graph_root:
        rel_root = config.rootpath.relative_to(opt.testfully_graph_root)
    else:
        # TODO: abstract out and support multiple VCS
        # the import graph is assumed to be full of repo-relative path
        # so we need to adjust in case of running tests in a subdir
        try:
            repo_root = (
                subprocess.check_output(
                    ["git", "rev-parse", "--show-toplevel"],
                    stdin=subprocess.DEVNULL,
                )
                .decode("utf-8")
                .rstrip()
            )
            rel_root = config.rootpath.relative_to(repo_root)
        except subprocess.CalledProcessError:
            # if we're not in a git repo, assume
            rel_root = None

    graph = load_import_graph(hook, opt.testfully_graph)

    if not opt.testfully_novalidate:
        config.pluginmanager.register(
            TestfullyValidate(hook, graph, rel_root),
            "TestfullyValidate",
        )

    if not opt.testfully_noselect:
        config.pluginmanager.register(
            TestfullySelect(hook, graph),
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
        self.files_to_validate: Set[str] = set()
        self.unexpected = (0, 0)

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_runtestloop(self, session):  # type: ignore
        res = yield

        u = (0, 0)
        for f in self.files_to_validate:
            # NB: fix test file location to be consistent with graph
            graph_path = str(self.rel_root / f) if self.rel_root else f
            import_path = f[:-3].replace("/", ".")

            expected = self.graph.file_depends_on(graph_path)
            actual = self.tracker.with_dynamic(import_path)

            if not expected or not actual:
                print(f"\nwarn: bad path mapping? {f} -> {import_path} / {graph_path}")

            unexpected = actual - (expected or set())
            if unexpected:
                session.ihook.pytest_warning_recorded.call_historic(
                    kwargs=dict(
                        warning_message=WarningMessage(
                            f"{len(unexpected)} unexpected imports {unexpected}",
                            Warning,
                            f,
                            0,
                        ),
                        when="runtest",
                        nodeid=f,
                        location=(f, 0, "<module>"),
                    )
                )
                u = (u[0] + 1, u[1] + len(unexpected))

        self.unexpected = u

        return res

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_sessionfinish(self, session):  # type: ignore
        self.tracker.stop_tracking()

        outcome = yield

        u = self.unexpected
        if u[0] > 0 and not session.config.option.testfully_warnonly:
            outcome.force_exception(
                pytest.exit.Exception(
                    f"{u[1]} unexpected import{'s' if u[1] > 1 else ''} "
                    f"in {u[0]} file{'s' if u[0] > 1 else ''}",
                    pytest.ExitCode.TESTS_FAILED,
                )
            )

        return outcome

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_runtest_logstart(self, nodeid, location):  # type: ignore
        f = location[0]
        self.files_to_validate.add(f)
        import_path = f[:-3].replace("/", ".")
        self.tracker.enter_context(import_path)

        return (yield)

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_runtest_logfinish(self, nodeid, location):  # type: ignore
        f = location[0]
        import_path = f[:-3].replace("/", ".")
        self.tracker.exit_context(import_path)

        return (yield)


class TestfullySelect:
    def __init__(self, hook: PluginHook, graph: ModuleGraph) -> None:
        self.hook = hook
        self.graph = graph

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)
    def pytest_collection_modifyitems(self, session, config, items):  # type: ignore
        # TODO
        return (yield)
