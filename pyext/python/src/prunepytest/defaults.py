# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is an implementation detail: there is no guarantee of forward
or backwards compatibility, even across patch releases.
"""

import os
import pathlib
import sys
import warnings
from fnmatch import fnmatch


from typing import cast, Any, Dict, Optional, Set, Tuple, Type, TypeVar


from .api import DefaultHook


DefaultHook_T = TypeVar("DefaultHook_T", bound=DefaultHook)


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
    # TODO: support poetry/hatch/pdm/...?
    filtered = pkg_roots

    f = toml_xtract(pyproject, "tool.setuptools.packages.find.where")
    if f:
        print(f"filter pkg roots according to setuptools.packages.find.where: {f}")
        filtered = {
            p
            for p in filtered
            if any(p.is_relative_to(pathlib.Path(search_path)) for search_path in f)
        }

    f = toml_xtract(pyproject, "tool.setuptools.packages.find.include")
    if f:
        print(f"filter pkg roots according to setuptools.packages.find.include: {f}")
        filtered = {
            p
            for p in filtered
            if any(fnmatch(str(p), pat) for pat in f) or p.name == "tests"
        }

    f = toml_xtract(pyproject, "tool.maturin.python-source")
    if f:
        print(f"filter pkg roots according to maturing python-source: {f}")
        filtered = {
            p
            for p in filtered
            if str(p).startswith(os.sep.join(f.split("/"))) or p.name == "tests"
        }

    f = toml_xtract(pyproject, "tool.maturin.python-packages")
    if f:
        print(f"filter pkg roots according to maturing python-packages: {f}")
        filtered = {p for p in filtered if p.name in f or p.name == "tests"}

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

    # TODO: check for pyproject.toml at multiple levels
    # ideally anywhere between root and the parent folder of each detected package root
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

        # fix trailing slash and other potential weirdness
        tst_paths = [os.path.normpath(p) for p in tst_paths]

        print(f"use testpaths from pyproject.toml: {tst_paths}")

        # TODO: merge instead of overriding?
        test_folders = {p: infer_py_pkg(p) for p in tst_paths}

        # ensure that those folders are included in source roots
        for fs, py in test_folders.items():
            local_ns.add(py.partition(".")[0])
            # NB: only add source root if it's not a subdir of existing roots
            # FIXME: what about existing roots being subdirs of the test dir?
            if fs not in source_roots and not any(
                fs.startswith(r + os.path.sep) for r in source_roots
            ):
                source_roots[fs] = py

    tst_file_pattern = toml_xtract(pyproj, "tool.pytest.ini_options.python_files")
    # FIXME: should we support lists fully instead of picking the first pattern?
    if isinstance(tst_file_pattern, list):
        tst_file_pattern = next(p for p in tst_file_pattern if "*" in p)

    print(
        f"default hook: {global_ns}, {local_ns}, {source_roots}, {test_folders}, {tst_file_pattern}"
    )
    return cls(global_ns, local_ns, source_roots, test_folders, tst_file_pattern)
