# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import pathlib

from typing import AbstractSet, List

import pytest
from _pytest.config import ExitCode

from ..api import BaseHook, PluginHook
from .util import actual_test_file, GraphLoader


class PruneSelector:
    """
    pytest hooks to deselect test cases based on import graph and modified files
    """

    def __init__(
        self,
        hook: PluginHook,
        graph: GraphLoader,
        modified: AbstractSet[str],
        rel_root: pathlib.Path,
    ) -> None:
        self.hook = hook
        self.graph = graph
        self.modified = modified
        self.rel_root = rel_root

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_collection_modifyitems(
        self, session: pytest.Session, config: pytest.Config, items: List[pytest.Item]
    ) -> None:
        n = len(items)
        skipped = []

        g = self.graph.get(session)
        affected = g.affected_by_files(self.modified) | self.modified

        covered_files = {}
        always_run = self.hook.always_run()

        # if the hook doesn't implement at least one of the methods related to dynamic imports
        # then check the import graph for files with dynamic imports
        # test files in that set will not be eligible for pruning
        has_unhandled_dyn_imports = (
            g.affected_by_modules({"importlib", "__import__"})
            if (
                self.hook.__class__.dynamic_dependencies
                is BaseHook.dynamic_dependencies
                and self.hook.__class__.dynamic_dependencies_at_leaves
                is BaseHook.dynamic_dependencies_at_leaves
            )
            else set()
        )

        if has_unhandled_dyn_imports:
            # TODO: pytest logging facility?
            print(
                f"WARN: disabling pruning for files with unhandled dynamic imports: {has_unhandled_dyn_imports}"
            )

        # safety: track if modified files are all in one of
        #  - in ModuleGraph
        #  - data files referenced in collected test items
        #  - file marked as always_run by hook
        #  - file marked as irrelevant by hook
        remaining = set(self.modified)

        # loop from the end to easily remove items as we go
        i = len(items) - 1
        while i >= 0:
            item = items[i]
            file, data = actual_test_file(item)

            # adjust path if graph_root != config.rootpath
            file = str(self.rel_root / file)
            data = str(self.rel_root / data) if data else data

            if file not in covered_files:
                covered_files[file] = g.file_depends_on(file) is not None

            if covered_files[file]:
                remaining.discard(file)
            if data:
                remaining.discard(data)

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
                or (data and data in always_run)
                or (item.name in always_run)
                or (file in has_unhandled_dyn_imports)
            )
            if not keep:
                skipped.append(item)
                del items[i]
            i -= 1

        remaining -= always_run
        remaining -= {x for x in remaining if g.file_depends_on(x) is not None}
        remaining = self.hook.filter_irrelevant_files(remaining)

        if remaining:
            # TODO: pytest logging facility?
            print(
                f"WARN: disabling pruning due to unhandled modified files: {remaining}"
            )
            items += skipped
        else:
            session.ihook.pytest_deselected(items=skipped)

        # TODO: select-only mode to measure impact
        if config.option.verbose >= 1:
            print(f"prunepytest: skipped={len(skipped)}/{n}")

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_sessionfinish(
        self, session: pytest.Session, exitstatus: ExitCode
    ) -> None:
        if exitstatus == ExitCode.NO_TESTS_COLLECTED:
            session.exitstatus = ExitCode.OK
