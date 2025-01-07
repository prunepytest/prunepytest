# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import os
import pathlib

from typing import AbstractSet, Dict, List, Optional, Set, Tuple

import pytest
import _pytest.unittest
import _pytest.nodes
from _pytest.config import ExitCode

from ..api import BaseHook, PluginHook
from ..graph import ModuleGraph
from ..vcs import VCS
from .util import actual_test_file, GraphLoader


UNSET: AbstractSet[str] = frozenset()


class _BaseSelector:
    def __init__(
        self,
        config: pytest.Config,
        hook: PluginHook,
        graph: GraphLoader,
        rel_root: pathlib.Path,
    ) -> None:
        self.config = config
        self.hook = hook
        self.graph = graph
        self.rel_root = rel_root

        self.rootpath = str(config.rootpath)

        # item -> (file, data) cache
        self.file_cache: Dict[_pytest.nodes.Node, Tuple[str, Optional[str]]] = {}
        # file -> bool (in graph)
        self.covered_files: Dict[str, bool] = {}
        self.always_run = self.hook.always_run()
        self.has_unhandled_dyn_imports: AbstractSet[str] = UNSET

        self.test_files: Set[str] = set()

    def file_cache_key(self, item: pytest.Item) -> _pytest.nodes.Node:
        if isinstance(item, (pytest.Function, _pytest.unittest.TestCaseFunction)):
            p = item.parent
            while p:
                if isinstance(p, pytest.File):
                    return p
                p = p.parent
        return item

    def actual_test_file(self, item: pytest.Item) -> Tuple[str, Optional[str]]:
        cache_key = self.file_cache_key(item)
        cached: Optional[Tuple[str, Optional[str]]] = self.file_cache.get(cache_key)
        if cached is not None:
            return cached

        file, data = actual_test_file(item)

        # make absolute paths relative to pytest root path
        if os.path.isabs(file):
            assert file.startswith(self.rootpath)
            file = file[len(self.rootpath) + 1 :]
        if data and os.path.isabs(file):
            assert data.startswith(self.rootpath)
            data = data[len(self.rootpath) + 1 :]

        # adjust path if graph_root != config.rootpath
        file = str(self.rel_root / file)
        data = str(self.rel_root / data) if data else data

        if file not in self.covered_files:
            g = self.graph.get(item.session)

            self.covered_files[file] = g.file_depends_on(file) is not None

            if self.has_unhandled_dyn_imports is UNSET:
                # if the hook doesn't implement at least one of the methods related to dynamic imports
                # then check the import graph for files with dynamic imports
                # test files in that set will not be eligible for pruning
                self.has_unhandled_dyn_imports = (
                    g.affected_by_modules({"importlib", "__import__"})
                    if (
                        self.hook.__class__.dynamic_dependencies
                        is BaseHook.dynamic_dependencies
                        and self.hook.__class__.dynamic_dependencies_at_leaves
                        is BaseHook.dynamic_dependencies_at_leaves
                    )
                    else frozenset()
                )

                if self.has_unhandled_dyn_imports:
                    # TODO: pytest logging facility?
                    print(
                        f"WARN: unhandled dynamic imports inhibit pruning: {self.has_unhandled_dyn_imports}"
                    )

        self.file_cache[cache_key] = (file, data)

        self.test_files.add(file)
        if data:
            self.test_files.add(data)

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
            or (data is not None and (data in affected or data in self.always_run))
            or (item.name in self.always_run)
            or (file in self.has_unhandled_dyn_imports)
            or (data is not None and (data in self.has_unhandled_dyn_imports))
        )

    def remaining(self, g: ModuleGraph, modified: AbstractSet[str]) -> AbstractSet[str]:
        # safety: are there modified files whose potential impact on tests cannot easily be assessed?
        # filter out:
        #   - test files referenced in pytest items
        #   - files that are part of the import graph
        #   - files marked as irrelevant by the hook
        #   - deleted files
        # everything else is suspect and out of an abundance of caution should trigger a full test run
        return {
            f
            for f in self.hook.filter_irrelevant_files(modified - self.test_files)
            if os.path.exists(f) and g.file_depends_on(f) is None
        }


class PruneSelector(_BaseSelector):
    """
    pytest hooks to deselect test cases based on import graph and modified files
    """

    def __init__(
        self,
        config: pytest.Config,
        hook: PluginHook,
        graph: GraphLoader,
        modified: AbstractSet[str],
        rel_root: pathlib.Path,
    ) -> None:
        super().__init__(config, hook, graph, rel_root)
        self.modified = modified

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_collection_modifyitems(
        self, session: pytest.Session, config: pytest.Config, items: List[pytest.Item]
    ) -> None:
        n = len(items)
        skipped = []

        g = self.graph.get(session)
        affected = g.affected_by_files(self.modified) | self.modified

        # loop from the end to easily remove items as we go
        i = len(items) - 1
        while i >= 0:
            item = items[i]
            if not self.should_keep(item, affected):
                skipped.append(item)
                del items[i]
            i -= 1

        remaining = self.remaining(g, self.modified)
        if remaining:
            # TODO: pytest logging facility?
            print(
                f"WARN: disabling pruning due to unhandled modified files: {remaining}"
            )
            items += skipped
        else:
            session.ihook.pytest_deselected(items=skipped)

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
        config: pytest.Config,
        hook: PluginHook,
        graph: GraphLoader,
        rel_root: pathlib.Path,
        vcs: VCS,
        commits: List[str],
    ) -> None:
        super().__init__(config, hook, graph, rel_root)
        self.vcs = vcs
        self.commits = commits

    @pytest.hookimpl(trylast=True)  # type: ignore
    def pytest_collection_modifyitems(
        self, session: pytest.Session, config: pytest.Config, items: List[pytest.Item]
    ) -> None:
        n = len(items)
        g = self.graph.get(session)

        n_unsafe = 0
        n_skipped = 0
        n_nogain = 0
        n_partial = 0
        relgain = []

        for c in self.commits:
            modified = set(self.vcs.modified_files(commit_id=c))

            if config.option.verbose >= 1:
                print(f"{c}:{modified}")

            affected = g.affected_by_files(modified) | modified
            relevant = self.hook.filter_irrelevant_files(affected)

            kept = 0
            pruned = 0

            for i in items:
                if self.should_keep(i, affected=relevant):
                    kept += 1
                else:
                    pruned += 1

            remaining = self.remaining(g, modified)
            if remaining:
                if config.option.verbose >= 1:
                    print(f"{c}:unsafe:{remaining}")
                n_unsafe += 1
            elif kept == 0:
                if config.option.verbose >= 1:
                    print(f"{c}:skipped:")
                n_skipped += 1
            elif pruned == 0:
                if config.option.verbose >= 1:
                    print(f"{c}:nogain:")
                n_nogain += 1
            else:
                if config.option.verbose >= 1:
                    print(f"{c}:gain:{pruned}:{float(pruned)/float(n)}")
                n_partial += 1
                relgain.append(float(pruned) / float(n))

        # print stats
        n_commits = len(self.commits)
        print(f"analyzed {n_commits} commits:")
        print(f" - {n_unsafe} unsafe to prune ({float(n_unsafe)/float(n_commits):.1%})")
        print(
            f" - {n_nogain} showed no benefit from pruning ({float(n_nogain)/float(n_commits):.1%})"
        )
        print(
            f" - {n_skipped} can be fully skipped ({float(n_skipped)/float(n_commits):.1%})"
        )
        print(
            f" - {n_partial} showed benefit from pruning ({float(n_partial)/float(n_commits):.1%})"
        )

        import statistics

        print("among commits that benefit from pruning:")
        print(f" - mean gain: {statistics.mean(relgain):.1%} test cases skipped")
        print(f" - median gain: {statistics.median(relgain):.1%} test cases skipped")
        if hasattr(statistics, "quantiles"):
            print(
                " - deciles of gain:",
                [f"{x:.1%}" for x in statistics.quantiles(relgain, n=10)],
            )

        # deselect everything to prevent running tests
        session.ihook.pytest_deselected(items=list(items))
        del items[:]
