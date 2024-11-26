import importlib.util
import os
import sys
import time
from typing import Any, Optional


from . import ModuleGraph

mono_ref = time.monotonic_ns()


def print_with_timestamp(*args, **kwargs) -> None:
    wall_elapsed_ms = (time.monotonic_ns() - mono_ref) // 1_000_000
    (
        kwargs['file'] if 'file' in kwargs else sys.stdout
    ).write("[+{: 8}ms] ".format(wall_elapsed_ms))
    print(*args, **kwargs)


def import_file(name: str, filepath: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, filepath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def is_test_file(name: str) -> bool:
    # https://docs.pytest.org/en/latest/explanation/goodpractices.html#test-discovery
    return (name.startswith("test_") and name.endswith('.py')) or name.endswith("_test.py")


def load_import_graph(hook, file: Optional[str]) -> ModuleGraph:
    # TODO: we could move most of this into a separate thread
    # load graph from file if provided, otherwise parse the repo
    if file and os.path.exists(file):
        print_with_timestamp("--- loading existing import graph")
        g = ModuleGraph.from_file(file)
    else:
        print_with_timestamp("--- building fresh import graph")
        g = ModuleGraph(
            hook.package_map(),
            hook.GLOBAL_NAMESPACES,     # unified namespace
            hook.LOCAL_NAMESPACES,      # per-pkg namespace
            getattr(hook, 'EXTERNAL_IMPORTS', set()) | {'importlib', '__import__'},
            getattr(hook, 'dynamic_dependencies', dict)()
        )

        unresolved = g.unresolved()
        if unresolved:
            print(f"unresolved: {unresolved}")

        if hasattr(hook, 'dynamic_dependencies_at_edges'):
            print_with_timestamp("--- computing dynamic dependencies")
            unified, per_pkg = hook.dynamic_dependencies_at_edges()
            print_with_timestamp("--- incorporating dynamic dependencies")
            g.add_dynamic_dependencies_at_edges(unified, per_pkg)

        if file:
            print_with_timestamp("--- saving import graph")
            g.to_file(file)

    return g
