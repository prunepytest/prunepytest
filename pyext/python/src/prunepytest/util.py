# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import importlib.util
import os
import pathlib
import sys
import time
from contextlib import contextmanager
from typing import cast, Any, Generator, Optional, Type, TypeVar


from .api import DefaultHook, BaseHook, ValidatorHook
from .defaults import hook_default
from .graph import ModuleGraph

Hook_T = TypeVar("Hook_T", bound=BaseHook)
DefaultHook_T = TypeVar("DefaultHook_T", bound=DefaultHook)


mono_ref = time.monotonic_ns()


def print_with_timestamp(*args: Any, **kwargs: Any) -> None:
    """
    Helper function to print to stdout, with a prefix indicating elapsed process time in millisecond
    """
    wall_elapsed_ms = (time.monotonic_ns() - mono_ref) // 1_000_000
    (kwargs["file"] if "file" in kwargs else sys.stdout).write(
        "[+{: 8}ms] ".format(wall_elapsed_ms)
    )
    print(*args, **kwargs)


def import_file(name: str, filepath: str) -> Any:
    """
    Import arbitrary Python code from a filepath

    This is used to import project-specific hooks that implement .api.Hook
    to alter the behavior of the pytest plugin or import-time validator

    :param name: name under which to import the module
    :param filepath: path of Python module to import
    :return: module object
    """
    spec = importlib.util.spec_from_file_location(name, filepath)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    assert mod
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@contextmanager
def chdir(d: str) -> Generator[None, None, None]:
    """simple context manager to change current working directory"""
    prev = os.getcwd()
    os.chdir(d)
    try:
        yield None
    finally:
        os.chdir(prev)


def load_import_graph(hook: BaseHook, file: Optional[str] = None) -> ModuleGraph:
    """
    Helper function to load a module import graph, either from a serialized
    file if available, or by parsing the relevant Python source code, based
    on a Hook specification
    """
    # TODO: we could move most of this into a separate thread
    # load graph from file if provided, otherwise parse the repo
    if file and os.path.exists(file):
        print_with_timestamp("--- loading existing import graph")
        g = ModuleGraph.from_file(file)
    else:
        print_with_timestamp("--- building fresh import graph")
        g = ModuleGraph(
            hook.source_roots(),
            hook.global_namespaces(),  # unified namespace
            hook.local_namespaces(),  # per-pkg namespace
            external_prefixes=hook.external_imports() | {"importlib", "__import__"},
            dynamic_deps=hook.dynamic_dependencies(),
            include_typechecking=hook.include_typechecking(),
        )

        unresolved = g.unresolved()
        if unresolved:
            print(f"unresolved: {unresolved}")

        print_with_timestamp("--- computing dynamic dependencies")
        per_pkg = hook.dynamic_dependencies_at_leaves()
        if per_pkg:
            print_with_timestamp("--- incorporating dynamic dependencies")
            g.add_dynamic_dependencies_at_leaves(per_pkg)

    return g


# NB: base_cls can be abstract, ignore mypy warnings at call site...
def load_hook(root: pathlib.Path, hook: str, base_cls: Type[Hook_T]) -> Hook_T:
    """
    Helper function to load a Hook implementation for a given base class

    If the given file has multiple Hook implementations, the first one that covers
    the requested type will be selected.

    Custom implementations may subclass DefaultHook, as long as their __init__
    method, if provided, has a signature compatible with that of DefaultHook.
    """
    hook_mod_name = "prunepytest._hook"
    hook_mod = import_file(hook_mod_name, str(root / hook))

    for name, val in hook_mod.__dict__.items():
        if (
            not hasattr(val, "__module__")
            or getattr(val, "__module__") != hook_mod_name
        ):
            continue
        if not isinstance(val, type):
            continue
        if not issubclass(val, base_cls):
            continue
        print(name, val)
        if issubclass(val, DefaultHook):
            return cast(Hook_T, hook_default(root, val))
        return val()

    raise ValueError(f"no implementation of {base_cls} found in {str(root / hook)}")


def load_hook_or_default(hook_path: Optional[str]) -> ValidatorHook:
    return (
        load_hook(pathlib.Path.cwd(), hook_path, ValidatorHook)  # type: ignore[type-abstract]
        if hook_path
        else hook_default(pathlib.Path.cwd())
    )
