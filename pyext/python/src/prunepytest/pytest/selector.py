# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import os
import pathlib
import subprocess

from typing import AbstractSet, Dict, List, Optional, Tuple

import pytest
from _pytest.config import ExitCode

from ..api import BaseHook, PluginHook
from ..vcs import VCS
from .util import actual_test_file, GraphLoader


class _BaseSelector:
    def __init__(
        self,
        hook: PluginHook,
        graph: GraphLoader,
        rel_root: pathlib.Path,
    ) -> None:
        self.hook = hook
        self.graph = graph
        self.rel_root = rel_root

        # item -> (file, data) cache
        self.file_cache: Dict[pytest.Item, Tuple[str, Optional[str]]] = {}
        # file -> bool (in graph)
        self.covered_files: Dict[str, bool] = {}
        self.always_run = self.hook.always_run()

    def actual_test_file(self, item: pytest.Item) -> Tuple[str, Optional[str]]:
        cached: Optional[Tuple[str, Optional[str]]] = self.file_cache.get(item)
        if cached is not None:
            return cached

        file, data = actual_test_file(item)

        # adjust path if graph_root != config.rootpath
        file = str(self.rel_root / file)
        data = str(self.rel_root / data) if data else data

        if file not in self.covered_files:
            self.covered_files[file] = (
                self.graph.get(item.session).file_depends_on(file) is not None
            )

        self.file_cache[item] = (file, data)
        return file, data

    def should_keep(self, item: pytest.Item, affected: AbstractSet[str]) -> bool:
        file, data = self.actual_test_file(item)

        # keep the test item if any of the following holds:
        # 1. python test file is not covered by the import graph
        # 2. python test file is affected by some modified file(s) according to the import graph
        # 3. data-driven test, and data file was modified
        # 4. file / test case marked as "always_run" by hook
        #
        # NB: at a later point, 3. could be extended by allowing explicit tagging of non-code
        # dependencies with some custom annotation (via comments collected by ModuleGraph, or
        # import-time hook being triggered a test collection time?)
        return (
            not self.covered_files[file]
            or (file in affected)
            or (file in self.always_run)
            or (data and (data in affected or data in self.always_run))
            or (item.name in self.always_run)
        )


class PruneSelector(_BaseSelector):
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
        super().__init__(hook, graph, rel_root)
        self.modified = modified

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_collection_modifyitems(
        self, session: pytest.Session, config: pytest.Config, items: List[pytest.Item]
    ) -> None:
        n = len(items)
        skipped = []

        g = self.graph.get(session)
        affected = g.affected_by_files(self.modified) | self.modified

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
            file, data = self.actual_test_file(item)

            if self.covered_files[file]:
                remaining.discard(file)
            if data:
                remaining.discard(data)

            keep = self.should_keep(item, affected) or (
                file in has_unhandled_dyn_imports
            )
            if not keep:
                skipped.append(item)
                del items[i]
            i -= 1

        remaining -= self.always_run
        remaining -= {x for x in remaining if g.file_depends_on(x) is not None}
        remaining = set(self.hook.filter_irrelevant_files(remaining))

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


class PruneImpact(_BaseSelector):
    """
    pytest hooks to compute selector impact across a range of commits

    NB: this is intentionally approximate for performance reasons:
     - instead of running the pruned test suite, we just count proportion of skipped tests
     - to reduce overhead, we avoid repeatedly changing the repo state
        - this means we also do not recompute the import graph for every commit, instead
          using the import graph of the HEAD commit to compute affected sets based on the
          modified set for each commit.
          This might result in under- or over-estimates for commits that significantly
          change the import graph
     - to reduce overhead, we avoid repeatedly running pytest collection
        - this may result in under- or over-estimates for commits that make significant
          changes to the test suite
    """

    def __init__(
        self,
        hook: PluginHook,
        graph: GraphLoader,
        rel_root: pathlib.Path,
        vcs: VCS,
        commit_list: Optional[str],
    ) -> None:
        super().__init__(hook, graph, rel_root)
        self.vcs = vcs
        self.commit_list = commit_list

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_collection_modifyitems(
        self, session: pytest.Session, config: pytest.Config, items: List[pytest.Item]
    ) -> None:
        if self.commit_list and os.path.exists(self.commit_list):
            with open(self.commit_list) as f:
                commits = f.read().splitlines()
        else:
            # TODO: use VCS interface
            # TODO: configurable commit depth
            commits = [
                l.partition(" ")[0]
                for l in subprocess.check_output(
                    ["git", "log", "--oneline", "-n", "20"]
                )
                .decode("utf-8")
                .splitlines()
            ]

        n = len(items)
        g = self.graph.get(session)

        for c in commits:
            modified = set(self.vcs.modified_files(commit_id=c))
            affected = g.affected_by_files(modified) | modified
            relevant = self.hook.filter_irrelevant_files(affected)

            print(f"> {c} {modified} {relevant}")

            types = (
                {os.path.splitext(f)[1] for f in relevant}
                - {".py", ".pyi", ".pyx"}
                - {".test"}
            )

            if types:
                print(f"{c}:unhandled{types}:+{n}:+{n}")
                continue

            kept = 0
            pruned = 0
            for i in items:
                if self.should_keep(i, affected=relevant):
                    kept += 1
                else:
                    pruned += 1

            print(f"{c}:pruned:+{kept}:+{n}")

        session.ihook.pytest_deselected(items=list(items))
        del items[:]
