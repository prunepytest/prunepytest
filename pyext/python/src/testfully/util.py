import importlib.util
import os
import pathlib
import sys
import time
from typing import cast, Any, Optional, Set, Tuple, Type, TypeVar

from . import ModuleGraph
from .api import ZeroConfHook, BaseHook


Hook_T = TypeVar("Hook_T", bound=BaseHook)
ZeroConfHook_T = TypeVar("ZeroConfHook_T", bound=ZeroConfHook)


mono_ref = time.monotonic_ns()


def print_with_timestamp(*args, **kwargs) -> None:
    wall_elapsed_ms = (time.monotonic_ns() - mono_ref) // 1_000_000
    (kwargs["file"] if "file" in kwargs else sys.stdout).write(
        "[+{: 8}ms] ".format(wall_elapsed_ms)
    )
    print(*args, **kwargs)


def import_file(name: str, filepath: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, filepath)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    assert mod
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def is_test_file(name: str) -> bool:
    # https://docs.pytest.org/en/latest/explanation/goodpractices.html#test-discovery
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith(
        "_test.py"
    )


def load_import_graph(hook: BaseHook, file: Optional[str]) -> ModuleGraph:
    # TODO: we could move most of this into a separate thread
    # load graph from file if provided, otherwise parse the repo
    if file and os.path.exists(file):
        print_with_timestamp("--- loading existing import graph")
        g = ModuleGraph.from_file(file)
    else:
        print_with_timestamp("--- building fresh import graph")
        g = ModuleGraph(
            hook.package_map(),
            hook.global_namespaces(),  # unified namespace
            hook.local_namespaces(),  # per-pkg namespace
            hook.external_imports() | {"importlib", "__import__"},
            hook.dynamic_dependencies(),
        )

        unresolved = g.unresolved()
        if unresolved:
            print(f"unresolved: {unresolved}")

        print_with_timestamp("--- computing dynamic dependencies")
        unified, per_pkg = hook.dynamic_dependencies_at_edges()
        if unified or per_pkg:
            print_with_timestamp("--- incorporating dynamic dependencies")
            g.add_dynamic_dependencies_at_edges(unified, per_pkg)

        if file:
            print_with_timestamp("--- saving import graph")
            g.to_file(file)

    return g


def find_package_roots(root: pathlib.PurePath) -> Set[pathlib.PurePath]:
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


def infer_ns_pkg(pkgroot: pathlib.PurePath) -> Tuple[pathlib.PurePath, str]:
    # walk down until first __init__.py without recognizable ns extend stanza

    from testfully import file_looks_like_pkgutil_ns_init

    ns = pkgroot.name
    first_non_ns = pkgroot
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
    return first_non_ns, ns


def hook_zeroconf(
    root: pathlib.PurePath,
    cls: Type[ZeroConfHook_T] = ZeroConfHook,  # type: ignore[assignment]
) -> ZeroConfHook_T:
    """
    Try to infer global and local namespaces, for sane zero-conf behavior
    """
    pkg_roots = find_package_roots(root)

    global_ns = set()
    local_ns = set()
    pkg_map = {}
    test_folders = {}

    for pkgroot in pkg_roots:
        if pkgroot.name == "tests":
            local_ns.add(pkgroot.name)
            test_folders[str(pkgroot.parent.relative_to(root))] = "tests"
            continue

        fs_path, py_path = infer_ns_pkg(pkgroot)

        global_ns.add(py_path.partition(".")[0])
        pkg_map[py_path] = str(fs_path.relative_to(root))

    return cls(global_ns, local_ns, pkg_map, test_folders)


# NB: base_cls can be abstract, ignore mypy warnings at call site...
def load_hook(root: pathlib.Path, hook: str, base_cls: Type[Hook_T]) -> Hook_T:
    hook_mod_name = "testfully._hook"
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
        if issubclass(val, ZeroConfHook):
            return cast(Hook_T, hook_zeroconf(root, val))
        return val()

    raise ValueError(f"no implementation of {base_cls} found in {str(root / hook)}")


# NB: base_cls can be abstract, ignore mypy warnings at call site...
def load_hook_if_exists(
    root: pathlib.Path, candidate: str, base_cls: Type[Hook_T]
) -> Hook_T:
    if (root / candidate).is_file():
        return load_hook(root, candidate, base_cls)

    assert issubclass(ZeroConfHook, base_cls)
    return cast(Hook_T, hook_zeroconf(root, ZeroConfHook))
