# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
pytest plugin for prunepytest

includes two parts:
 - a test case selector, based on import graph and modified files
 - a validator to flag unexpected imports, providing confidence that test (de)selection is sound

The flags added by this module to pytest are part of the public API, and expected
to remain stable across minor and patch releases.

The rest of this module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import os

import pathlib
import pytest

from typing import Any

from _pytest.tmpdir import TempPathFactory

from ..api import PluginHook, DefaultHook
from ..defaults import hook_default
from ..util import load_hook
from ..vcs.detect import detect_vcs
from .util import GraphLoader, has_xdist


def pytest_addoption(parser: Any, pluginmanager: pytest.PytestPluginManager) -> None:
    group = parser.getgroup("prunepytest")

    group.addoption(
        "--prune",
        action="store_true",
        dest="prune",
        help=("Enable prunepytest plugin"),
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
        "--prune-modified",
        action="store",
        type=str,
        dest="prune_modified",
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
        raise ValueError("prunepytest requires pluggy>=1.2")

    vcs = detect_vcs()

    graph_root = opt.prune_graph_root or (
        vcs.repo_root() if vcs else str(config.rootpath)
    )
    rel_root = config.rootpath.relative_to(graph_root)

    graph_path = opt.prune_graph
    if graph_path and not os.path.isfile(graph_path):
        graph_path = None

    if has_xdist and config.pluginmanager.has_plugin("xdist"):
        graph_path = add_xdist_hook(config, graph_path)

    if opt.prune_hook:
        hook = load_hook(config.rootpath, opt.prune_hook, PluginHook)  # type: ignore[type-abstract]
        hook.setup()
    else:
        hook = hook_default(config.rootpath, DefaultHook)

    graph = GraphLoader(config, hook, graph_path, graph_root)

    if not opt.prune_novalidate:
        from .validator import PruneValidator

        config.pluginmanager.register(
            PruneValidator(hook, graph, rel_root),
            "PruneValidator",
        )

    if not opt.prune_noselect:
        if opt.prune_modified is not None:
            modified = opt.prune_modified.split(",")
        elif vcs:
            modified = (
                vcs.modified_files(base_commit=opt.prune_base_commit)
                + vcs.dirty_files()
            )
        else:
            raise ValueError("unsupported VCS for test selection...")

        print(f"modified: {modified}")

        from .selector import PruneSelector

        config.pluginmanager.register(
            PruneSelector(hook, graph, set(modified) - {""}, rel_root),
            "PruneSelector",
        )


def add_xdist_hook(config: pytest.Config, graph_path: str) -> str:
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

    return graph_path
