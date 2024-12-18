# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import sys

from typing import Set

from .args import parse_args, Arg, ArgValues
from .util import load_hook_or_default, load_import_graph


USAGE = """
usage: python -m prunepytest <cmd> [options...]

Available commands:
  hook [<path>]
  graph [--hook <path>] [--graph <path>]
  modified [--base-commit <commit_id>]
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
