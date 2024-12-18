# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

import importlib.util
import os
import pathlib
import sys
import time
import warnings
from contextlib import contextmanager
from fnmatch import fnmatch
from typing import cast, Any, Dict, Generator, Optional, Set, Tuple, Type, TypeVar


from .graph import ModuleGraph
from .api import DefaultHook, BaseHook, ValidatorHook

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


def find_package_roots(root: pathlib.PurePath) -> Set[pathlib.PurePath]:
    """
    Helper function to find the root paths of Python packages within a file tree
    """
    # TODO: parallel rust implementation?
    pkgs = set()
    with os.scandir(root) as it:
        for dent in it:
            if not dent.is_dir(follow_symlinks=False) or dent.name.startswith("."):
                continue
            child = root / dent.name
            if os.path.isfile(child / "__init__.py"):
                pkgs.add(child)
            else:
                pkgs.update(find_package_roots(child))
    return pkgs


def infer_py_pkg(filepath: str) -> str:
    """
    Given the file path to a Python module, infer the corresponding Python import path

    NB: This relies on the presence of explicit __init__.py
    """
    parent = os.path.dirname(filepath)
    while parent and os.path.exists(os.path.join(parent, "__init__.py")):
        parent = os.path.dirname(parent)
    return filepath[len(parent) + 1 if parent else 0 :].replace("/", ".")


def infer_ns_pkg(
    pkgroot: pathlib.PurePath, root: Optional[pathlib.PurePath] = None
) -> Tuple[pathlib.PurePath, str]:
    """
    Helper function to recognize pkgutil-style namespace packages
    """
    # walk down until first __init__.py without recognizable ns extend stanza

    from ._prunepytest import file_looks_like_pkgutil_ns_init

    ns = pkgroot.name
    first_non_ns = root / pkgroot if root else pkgroot
    while file_looks_like_pkgutil_ns_init(str(first_non_ns / "__init__.py")):
        with os.scandir(first_non_ns) as it:
            sub = [
                c.name
                for c in it
                # TODO: also filter out hidden?
                if c.is_dir(follow_symlinks=False) and c.name != "__pycache__"
            ]
        if len(sub) == 1:
            ns += "."
            ns += sub[0]
            first_non_ns = first_non_ns / sub[0]
        else:
            # bail if we don't have a clean match
            return pkgroot, pkgroot.name
    return first_non_ns.relative_to(root) if root else first_non_ns, ns


def parse_toml(filepath: str) -> Dict[str, Any]:
    """Helper function to parse a file in TOML format"""
    pyver = sys.version_info
    target = "tomllib" if pyver[0] == 3 and pyver[1] >= 11 else "tomli"
    try:
        tomllib = __import__(target)
    except ImportError:
        warnings.warn(f"unable to parse {filepath}, consider installing tomli")
        return {}

    with open(filepath, "rb") as f:
        return cast(Dict[str, Any], tomllib.load(f))


def toml_xtract(cfg: Dict[str, Any], cfg_path: str) -> Any:
    """helper function to extract nested values by path within a parsed TOML config"""
    head, _, tail = cfg_path.partition(".")
    if head not in cfg:
        return None
    if tail:
        return toml_xtract(cfg[head], tail)
    return cfg[head]


def filter_packages(
    pkg_roots: Set[pathlib.PurePath], pyproject: Dict[str, Any]
) -> Set[pathlib.PurePath]:
    """
    Given a set of package roots, and a parsed pyproject.toml, filter out
    irrelevant source roots

    This is a best-effort approach to handle projects with slight deviations
    from conventional source layouts, to maximize the applicability of the
    default Hook implementation. For more complicated cases, custom Hook
    implementations may be warranted.
    """
    # TODO: support poetry/hatch/maturin/...?
    filtered = pkg_roots

    f = toml_xtract(pyproject, "tool.setuptools.packages.find.include")
    if f:
        print(f"filter pkg roots according to setuptools config: {f}")
        filtered = {p for p in filtered if any(fnmatch(str(p), pat) for pat in f)}

    return filtered


def hook_default(
    root: pathlib.PurePath,
    cls: Type[DefaultHook_T] = DefaultHook,  # type: ignore[assignment]
) -> DefaultHook_T:
    """
    Constructs a DefaultHook, configured with sane defaults based on
    scanning the contents of the given root path
    """
    # make paths relative to root for easier manipulation
    pkg_roots = {r.relative_to(root) for r in find_package_roots(root)}

    pyproj_path = str(root / "pyproject.toml")
    pyproj = parse_toml(pyproj_path) if os.path.exists(pyproj_path) else {}

    if pyproj:
        pkg_roots = filter_packages(pkg_roots, pyproj)

    global_ns = set()
    local_ns = set()
    source_roots = {}
    test_folders = {}

    for pkgroot in pkg_roots:
        if pkgroot.name == "tests":
            local_ns.add(pkgroot.name)
            test_folders[str(pkgroot)] = "tests"
            source_roots[str(pkgroot)] = "tests"
            continue

        fs_path, py_path = infer_ns_pkg(pkgroot, root)

        global_ns.add(py_path.partition(".")[0])
        source_roots[str(fs_path)] = py_path

    # TODO: also check pytest.ini?
    tst_paths = toml_xtract(pyproj, "tool.pytest.ini_options.testpaths")
    if tst_paths:
        if not isinstance(tst_paths, list):
            tst_paths = [tst_paths]
        print(f"use testpaths from pyproject.toml: {tst_paths}")
        # TODO: ensure that those are included in source roots
        # TODO: merge instead of overriding?
        test_folders = {p: infer_py_pkg(p) for p in tst_paths}

    tst_file_pattern = toml_xtract(pyproj, "tool.pytest.ini_options.python_files")

    print(
        f"default hook: {global_ns}, {local_ns}, {source_roots}, {test_folders}, {tst_file_pattern}"
    )
    return cls(global_ns, local_ns, source_roots, test_folders, tst_file_pattern)


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
