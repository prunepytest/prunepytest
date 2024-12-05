"""
Usage: python -m testfully.validator <path/to/hook.py> [<path/to/serialized/graph>]

Purpose:

This file is part of a multi-prong system to validate the soundness of testfully
for a given codebase.

Specifically, it is concerned with validating that the transitive closure
of dependencies for a set of test files is computed properly, to give
confidence in the computation of its transpose: the set of affected tests to
run given a set of modified files.

Python import tracking is a *very hard* problem, because arbitrary Python
code can be executed at import time, and arbitrary imports can be loaded
at run time! We deal with that as follows:

 - the rust parser goes deep, extracting import statements even in code that
   might never be executed (it does however ignore typechecking-only
   imports). These are not going to be reported by the Python validator
   and that's OK. Better to have false positives (detected imports that
   are not used) than false negatives (undetected imports).

 - this validator actually runs arbitrary python code during import
   tracking, because that's how Python rolls, so it is able to find
   dynamically-loaded imports, provided they are resolved at import-time
   (i.e. triggered by a module-level statement). This is good as it shows
   blind spots in the rust parser and gives us an opportunity to make those
   dynamic dependencies explicit. This is useful as a first pass before
   attempting to actually run tests under testfully as it gives quicker,
   though less accurate, feedback on the use of dynamic dependencies.

 - the pytest plugin tracks imports while tests are actually running, and
   is able to enforce that no unexpected imports are used.


"""

import contextlib
import importlib
import importlib.util
import io
import os
import pathlib
import sys
import traceback

from typing import Callable, Dict, Set, Optional, Tuple

from . import ModuleGraph
from .api import ValidatorHook
from .tracker import Tracker, print_clean_traceback
from .util import (
    print_with_timestamp,
    load_import_graph,
    is_test_file,
    load_hook_if_exists,
)


def import_with_capture(fq: str, c_out: bool, c_err: bool) -> None:
    with io.StringIO() as f:
        with contextlib.redirect_stdout(
            f
        ) if c_out else contextlib.nullcontext(), contextlib.redirect_stderr(
            f
        ) if c_err else contextlib.nullcontext():
            try:
                importlib.__import__(fq, fromlist=())
            except:
                if c_out or c_err:
                    print_with_timestamp(f"--- captured output for: {fq}")
                    sys.stderr.write(f.getvalue())
                raise


def recursive_import_tests(
    path: str, import_prefix: str, hook: ValidatorHook, errors: Dict[str, BaseException]
) -> Set[str]:
    imported = set()

    # process __init__.py first if present
    init_py = os.path.join(path, "__init__.py")
    if os.path.exists(init_py):
        try:
            import_with_capture(
                import_prefix,
                hook.should_capture_stdout(),
                hook.should_capture_stderr(),
            )
        except BaseException as ex:
            # NB: this should not happen, report so it can be fixed and proceed
            errors[init_py] = ex

    with os.scandir(path) as it:
        for e in it:
            if e.is_dir():
                imported |= recursive_import_tests(
                    e.path, import_prefix + "." + e.name, hook, errors
                )
            elif e.is_file() and is_test_file(e.name):
                hook.before_file(e, import_prefix)
                fq = import_prefix + "." + e.name[:-3]
                try:
                    import_with_capture(
                        fq, hook.should_capture_stdout(), hook.should_capture_stderr()
                    )
                    imported.add(fq)
                except BaseException as ex:
                    # NB: this should not happen, report so it can be fixed and proceed
                    errors[e.path] = ex
                hook.after_file(e, import_prefix)

    return imported


def validate_subset(
    py_tracked: Dict[str, Set[str]],
    rust_graph: ModuleGraph,
    filter_fn: Callable[[str], bool],
    package: Optional[str] = None,
) -> int:
    diff_count = 0
    for module, pydeps in py_tracked.items():
        if not filter_fn(module):
            continue
        rdeps = rust_graph.module_depends_on(module, package) or frozenset()

        # NB: we only care about anything that the rust code might be missing
        # it's safe to consider extra dependencies, and in fact expected since
        # the rust parser goes deep and tracks import statements inside code
        # that might never get executed whereas by design the python validation
        # will only track anything that gets executed during the import phase
        rust_missing = pydeps - rdeps
        if rust_missing:
            diff_count += 1
            print(
                f"{module} rust {len(rdeps)} / py {len(pydeps)}: rust missing {len(rust_missing)} {rust_missing}"
            )
    return diff_count


def validate_folder(
    base: str, sub: str, hook: ValidatorHook, t: Tracker, g: ModuleGraph
) -> Tuple[int, int]:
    # print_with_timestamp(f"--- {base}")
    # put package path first in sys.path to ensure finding test files
    sys.path.insert(0, os.path.abspath(base))
    old_k = set(sys.modules.keys())

    hook.before_folder(base, sub)

    errors: Dict[str, BaseException] = {}

    # we want to import every test file in that package, recursively,
    # while preserving the appropriate import name, to allow for:
    #  - resolution of __init__.py
    #  - resolution of test helpers, via absolute or relative import
    imported = recursive_import_tests(os.path.join(base, sub), sub, hook, errors)

    if errors:
        print(f"{len(errors)} exceptions encountered!")

        for filepath, ex in errors.items():
            print_with_timestamp(f"--- {filepath}")
            print(f"{type(ex)} {ex}")
            print_clean_traceback(traceback.extract_tb(ex.__traceback__))

    with_dynamic = {}
    for m in imported:
        with_dynamic[m] = t.with_dynamic(m)

    # NB: do validation at the package level for the test namespace
    # this is necessary because it is not a unified namespace. There can be
    # conflicts between similarly named test modules across packages.
    #
    # NB: we only validate test files, not test helpers. This is because, for
    # performance reason, dynamic dependencies are only applied to nodes of the
    # import graphs that do not have any ancestors (i.e modules not imported by
    # any other module)
    # This is fine because the purpose of this validation is to ensure that we
    # can determine a set of affected *test files* from a given set of modified
    # files, so as long as we validate that tests have matching imports between
    # python and Rust, we're good to go.
    def is_local_test_module(module: str) -> bool:
        last = module.rpartition(".")[2]
        return module.startswith(sub) and (
            last.startswith("test_") or last.endswith("_test")
        )

    num_mismatching_files = validate_subset(
        with_dynamic, g, package=base, filter_fn=is_local_test_module
    )

    # cleanup to avoid contaminating subsequent iterations
    sys.path = sys.path[1:]
    new_k = sys.modules.keys() - old_k
    for m in new_k:
        if m.partition(".")[0] == sub:
            del t.tracked[m]
            if m in t.dynamic_users:
                del t.dynamic_users[m]
            del sys.modules[m]

    hook.after_folder(base, sub)

    return len(errors), num_mismatching_files


def validate(hook_path: str, graph_path: Optional[str]) -> Tuple[int, int]:
    hook = load_hook_if_exists(pathlib.Path.cwd(), hook_path, ValidatorHook)  # type: ignore[type-abstract]

    t = Tracker()
    t.start_tracking(
        hook.global_namespaces() | hook.local_namespaces(),
        patches=hook.import_patches(),
        record_dynamic=True,
        dynamic_anchors=hook.dynamic_anchors(),
        dynamic_ignores=hook.dynamic_ignores(),
        log_file=hook.tracker_log(),
    )

    # NB: must be called after tracker, before module graph
    hook.setup()

    g = load_import_graph(hook, graph_path)

    # keep track or errors and import differences
    files_with_missing_imports = 0
    error_count = 0

    # TODO: user-defined order (toposort of package dep graph...)
    print_with_timestamp("--- tracking python imports")
    for base, sub in sorted(hook.test_folders().items()):
        assert sub in hook.local_namespaces(), f"{sub} not in {hook.local_namespaces()}"

        # some packages do not have tests, simply skip them
        if not os.path.isdir(os.path.join(base, sub)):
            continue

        n_errors, n_mismatching_files = validate_folder(base, sub, hook, t, g)

        files_with_missing_imports += n_mismatching_files
        error_count += n_errors

    t.stop_tracking()

    if t.dynamic and hook.record_dynamic():
        print_with_timestamp("--- locations of dynamic imports")
        dedup_stack = set()
        for dyn_stack in t.dynamic:
            as_tuple = tuple((f.filename, f.lineno) for f in dyn_stack)
            if as_tuple in dedup_stack:
                continue
            dedup_stack.add(as_tuple)
            print("---")
            traceback.print_list(dyn_stack, file=sys.stdout)

    # validate global namespace once all packages have been processed
    print_with_timestamp("--- comparing code import graphs")
    files_with_missing_imports += validate_subset(
        t.tracked,
        g,
        filter_fn=lambda module: module.partition(".")[0] in hook.global_namespaces(),
    )

    return error_count, files_with_missing_imports


if __name__ == "__main__":
    n_err, m_missing = validate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

    print_with_timestamp("--- validation result")
    if n_err + m_missing == 0:
        print("The rust module graph can be trusted")
        sys.exit(0)
    else:
        if m_missing:
            print("The rust module graph is missing some imports")
            print("You may need to make some dynamic imports explicit")
        if n_err:
            print("Errors prevented validation of the rust module graph")
            print("Fix them and try again...")
        sys.exit(1)
