# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

from dataclasses import dataclass, fields
from enum import Enum
import sys
import argparse

from typing import cast, AbstractSet, Any, Dict, List, Optional


class Arg(Enum):
    hook_path = "hook"
    graph_path = "graph"
    modified = "modified"
    base_commit = "base-commit"

    def option_string(self) -> List[str]:
        v: str = self.value
        return [
            "--" + v,  # long option
            "--prune-" + v,  # long option, for consistency with pytest plugin
        ]

    def __lt__(self, other: Enum) -> bool:
        # TODO: use definition order instead?
        return cast(bool, self.value < other.value)


@dataclass
class ArgValues:
    hook_path: Optional[str] = None
    graph_path: Optional[str] = None
    modified: Optional[List[str]] = None
    base_commit: Optional[str] = None


def _is_optional_type(t: Any) -> bool:
    return cast(bool, t == Optional[t])


def _transform(v: str, t: Any) -> Any:
    if _is_optional_type(t):
        t = t.__args__[0]
    if v is not None and t == List[str]:
        return v.split(",")
    return v


_arg_types: Dict[Arg, Any] = {Arg[f.name]: f.type for f in fields(ArgValues)}


def parse_args(
    args: List[str],
    supported_args: AbstractSet[Arg] = frozenset(),
    allow_unknown: bool = False,
) -> ArgValues:
    p = argparse.ArgumentParser()

    for a in sorted(supported_args):
        t = _arg_types[a]
        p.add_argument(*a.option_string(), required=not _is_optional_type(t))

    valid, rest = p.parse_known_args(args)

    if not allow_unknown and rest:
        print("unknown arguments: %s" % rest)
        sys.exit(2)

    return ArgValues(
        **{
            a.name: _transform(getattr(valid, a.value.replace("-", "_")), _arg_types[a])
            for a in supported_args
        }
    )
