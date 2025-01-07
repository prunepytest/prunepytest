# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import os
import subprocess
import sys

from typing import Set, Callable, List, Tuple

from typing_extensions import AbstractSet

from .api import PluginHook
from .args import parse_args, Arg, ArgValues
from .graph import ModuleGraph
from .util import load_hook_or_default, load_import_graph
from .vcs import VCS
from .vcs.detect import detect_vcs


USAGE = """
usage: python -m prunepytest <cmd> [options...]

Available commands:
  hook [<path>]
  graph [--hook <path>] [--graph <path>]
  modified [--base-commit <commit_id>]
  depends [--hook <path>] [--graph <path>] modules/files...
  affected [--hook <path>] [--graph <path>] [--base-commit <commit_id>]
  validate [--hook <path>] [--graph <path>]
  help
"""


def _modified(p: ArgValues) -> Set[str]:
    from .vcs.detect import detect_vcs

    vcs = detect_vcs()
    if not vcs:
        print("no vcs detected, specify modified files explicitly.", file=sys.stderr)
        sys.exit(1)
    return set(vcs.modified_files(base_commit=p.base_commit)) | set(vcs.dirty_files())


def recursive_find_py(
    path: str, is_test_file: Callable[[str], bool]
) -> Tuple[List[str], List[str]]:
    py = []
    tst = []
    with os.scandir(path) as it:
        for e in it:
            if e.is_dir():
                a, b = recursive_find_py(e.path, is_test_file)
                py.extend(a)
                tst.extend(b)
            elif e.is_file() and e.name.endswith(".py"):
                if is_test_file(e.name):
                    tst.append(e.path)
                else:
                    py.append(e.path)
    return py, tst


def _impact(
    h: str,
    vcs: VCS,
    hook: PluginHook,
    graph: ModuleGraph,
    source_roots: AbstractSet[str],
    all_tests: AbstractSet[str],
):
    modified = set(vcs.modified_files(h))
    relevant = hook.filter_irrelevant_files(modified)

    # types of files modified
    types = {os.path.splitext(f)[1] for f in relevant}

    if ".py" in types or any(
        any(f.startswith(r + os.path.sep) for r in source_roots) for f in relevant
    ):
        types -= {".py", ".pyi", ".pyx"}

        if types:
            print(f"{h}:pyand:+0")
        else:
            affected = graph.affected_by_files(relevant) | relevant
            # NB
            tests = {f for f in affected if f in all_tests}

            # TODO: it'd be nice to be able to perform collection once
            # and then adjust the pruning without repeatedly collecting...
            subprocess.check_output(["pytest", "--prune", "--setup-plan"])
            print(f"{h}:pyonly:-{len(all_tests)-len(tests)}")
    else:
        print(f"{h}:nopy:+0")
        pass


def main() -> None:
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(0)

    cmd = sys.argv[1]
    if cmd == "hook":
        # TODO: argparse help handling
        hook = load_hook_or_default(sys.argv[2] if len(sys.argv) > 2 else None)
        # TODO: print some debug information?
        print(hook)
    elif cmd == "graph":
        p = parse_args(sys.argv[2:], supported_args={Arg.hook_path, Arg.graph_path})
        hook = load_hook_or_default(p.hook_path)
        graph = load_import_graph(hook, p.graph_path)
        dyn = {
            f
            for f in graph.affected_by_modules(["importlib", "__import__"])
            if hook.is_test_file(f.rpartition(".")[2] + ".py")
        }
        if dyn:
            print(
                f"{len(dyn)} test files potentially affected by dynamic imports!\n{dyn}"
            )
        if p.graph_path:
            graph.to_file(p.graph_path)
    elif cmd == "modified":
        p = parse_args(sys.argv[2:], supported_args={Arg.base_commit})
        print(_modified(p))
    elif cmd == "depends":
        p = parse_args(
            sys.argv[2:],
            supported_args={Arg.hook_path, Arg.graph_path},
            allow_unknown=True,
        )
        hook = load_hook_or_default(p.hook_path)
        graph = load_import_graph(hook, p.graph_path)
        for m in p._rest:
            print(
                f"{m} : {graph.file_depends_on(m) if '/' in m else graph.module_depends_on(m)}"
            )
    elif cmd == "affected":
        p = parse_args(
            sys.argv[2:],
            supported_args={
                Arg.hook_path,
                Arg.graph_path,
                Arg.modified,
                Arg.base_commit,
            },
        )
        hook = load_hook_or_default(p.hook_path)
        graph = load_import_graph(hook, p.graph_path)
        modified = set(p.modified) if p.modified else _modified(p)
        affected = graph.affected_by_files(modified) | modified
        print(affected)
    elif cmd == "impact":
        p = parse_args(
            sys.argv[2:],
            supported_args={
                Arg.hook_path,
                Arg.graph_path,
            },
        )
        vcs = detect_vcs()
        hook = load_hook_or_default(p.hook_path)
        graph = load_import_graph(hook, p.graph_path)
        source_roots = hook.source_roots().keys()

        all_tests = set()
        for r in source_roots:
            code, test = recursive_find_py(r, hook.is_test_file)
            all_tests.update(set(test))

        for h in p._rest:
            _impact(h, vcs, hook, graph, source_roots, all_tests)

    elif cmd == "validate":
        from . import validator

        validator.main(sys.argv[2:])
    elif cmd in {"help", "-help", "-h", "--help"}:
        print(USAGE)
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        print()
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    main()
