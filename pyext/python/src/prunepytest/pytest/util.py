# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import os

from typing import cast, Any, Generator, Optional, Tuple

import pytest
import _pytest.unittest

from ..api import PluginHook
from ..graph import ModuleGraph
from ..util import chdir, load_import_graph


# detect xdist and adjust behavior accordingly
try:
    from xdist import is_xdist_controller  # type: ignore[import-not-found]

    has_xdist = True
except ImportError:
    has_xdist = False

    def is_xdist_controller(session: pytest.Session) -> bool:
        return False


def safe_is_xdist_controller(session: pytest.Session) -> bool:
    try:
        # NB: dsession is the name used by pytest-xdist to manage distributed testing
        # check if the plugin is active before attempting to assess controller status
        return session.config.pluginmanager.hasplugin("dsession") and cast(
            bool, is_xdist_controller(session)
        )
    except AttributeError:
        # if the plugin is present but explicitly disabled...
        return False


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

    # for normal functions, filepath is best obtained by walking up the collection tree
    # to the Module, rather than resolving the actual location of the underlying code
    # for more exotic collection setups, for instance data-drive test cases as seen in
    # mypy's repo, we do want to extract the most accurate location data possible
    f = (
        None
        if isinstance(item, (pytest.Function, _pytest.unittest.TestCaseFunction))
        else item.location[0]
    )

    p = item.parent
    while p:
        if isinstance(p, pytest.File):
            return str(p.path), f
        p = p.parent

    return f if f else item.location[0], None


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

            rel_root = self.config.rootpath.relative_to(self.graph_root)

            with chdir(self.graph_root):
                graph = load_import_graph(self.hook, load_path, rel_root=rel_root)

            if safe_is_xdist_controller(session) and not load_path:
                print(f"saving import graph to {self.graph_path}")
                graph.to_file(self.graph_path)

        return graph


class _XdistHelper:
    def __init__(
        self,
        graph: GraphLoader,
    ) -> None:
        self.graph = graph

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

    @pytest.hookimpl(tryfirst=True, hookwrapper=True)  # type: ignore
    def pytest_sessionstart(
        self, session: pytest.Session
    ) -> Generator[Any, None, None]:
        if safe_is_xdist_controller(session):
            self.is_controller = True
            # ensure the import graph is computed before the workers need it
            self.graph.get(session)

        return (yield)
