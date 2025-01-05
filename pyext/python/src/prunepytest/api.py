# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is a public API: it is expected that compatibility will be
preserved across minor and patch releases.
"""

import os
from abc import ABC, abstractmethod, ABCMeta
from fnmatch import fnmatch

from typing import AbstractSet, Any, Mapping, Optional, Sequence, Set, Tuple


class BaseHook(ABC):
    """
    API surface to create a ModuleGraph object
    """

    def setup(self) -> None:
        """
        setup() is called once, after the Hook object is created, and before it
        is used by either the pytest plugin or the import-time validator.

        Crucially, it is called *after* creating a Tracker object, but before any
        other Hook methods are invoked, which means it is the first point where it
        is safe to import project-specific code
        """
        pass

    @abstractmethod
    def global_namespaces(self) -> AbstractSet[str]:
        """
        returns a set of python import path prefixes to be collected by ModuleGraph,
        and tracked by Tracker

        entries in this set form a unified "global" namespace that might be spread
        across multiple distinct file trees, where duplicate import paths cannot
        exist in separate subtrees
        """
        ...

    @abstractmethod
    def local_namespaces(self) -> AbstractSet[str]:
        """
        returns a set of python import path prefixes to be collected by ModuleGraph,
        and tracked by Tracker

        entries in this set form fragmented "local" namespace that might be spread
        across multiple distinct file trees, where duplicate import paths are allowed
        to exist in separate subtrees, and each individual subtree is isolated, being
        only allowed to refer to import path in itself, or in the global namespace,
        but not to any other local namespaces.
        """
        ...

    @abstractmethod
    def source_roots(self) -> Mapping[str, str]:
        """
        returns a mapping from filesystem path to corresponding python import prefix

        All paths in this mapping will be recursively searched for python code to parse
        and extract import data from.

        This mapping includes paths for both global and local namespaces.

        The python import prefixes MUST be unique for file trees that belong in the global
        namespace. No such restriction exists for file trees that belong to the local
        namespace.
        """
        ...

    def include_typechecking(self) -> bool:
        """
        whether to skip collecting import statements guarded by `if TYPE_CHECKING`
        statements.

        Such imports are ignored by default, but some packages might need them to be
        collected to compute an accurate import graph. This is true of pydantic v2
        for instance, which does a fair amount of dynamic import magic in its __init__.py
        and makes that legible through type-checking-gated imports.
        """
        return False

    def external_imports(self) -> AbstractSet[str]:
        """
        returns a set of python import prefix to be collected by ModuleGraph,
        and tracked by Tracker

        This is intended for import path that do not have corresponding Python source code,
        either because they are external to the project under test, or because they point
        to native code extensions.
        """
        return frozenset()

    def dynamic_dependencies(self) -> Mapping[str, AbstractSet[str]]:
        """
        returns extra dependency information to be added to ModuleGraph after parsing
        the Python code, to account for use of dynamic imports inside the code.

        The keys of this mapping may be either python import paths, or file paths.
        Either way, they must point to Python module that are part of the collected
        import graph, either directly (valid source files under the input source_roots)
        or indirectly (referred to in an import statement within valid source files under
        the input source_roots).

        The values are sets of Python import paths to be considered as extra direct
        (dynamic) dependencies of the corresponding module.

        These extra dependency edges are added to ModuleGraph before computing the
        transitive closure and are therefore propagated automatically across the whole
        import graph.
        """
        return {}

    def dynamic_dependencies_at_leaves(
        self,
    ) -> Sequence[Tuple[str, Mapping[str, AbstractSet[str]]]]:
        """
        returns extra dependency information to be added to ModuleGraph after parsing
        the Python code, to account for use of dynamic imports inside the code.

        This is intended to account for dynamic dependencies that are incurred by modules
        within the global namespace but whose actual reach might *vary* across source
        roots.

        In that case, we cannot simply incorporate dynamic dependencies directly within
        the global namespace. Instead, we only want to affect *leaves* of the import
        graph (i.e. modules that are not imported by any other module, which typically
        means test files or command line entry points). This in turns means we need to
        add those *after* computing the transitive closure, which means the order in
        which they are added matters, hence the use of a sequence of item, instead of
        a mapping.

        The first key of each item (i.e. the first element of the tuple), is a Python
        import path, or file path, as in dynamic_dependencies. The second key, in the
        mapping, is the filesystem path to a source root, as each source root now gets
        a distinct set of dynamic dependencies. The value, in the mapping, is a set of
        extra direct dependencies to be added to the import graph.
        """
        return tuple()


class TrackerMixin:
    """
    API surface to configure a Tracker object
    """

    def import_patches(self) -> Optional[Mapping[str, Any]]:
        """
        returns a set of patches to apply immediately after importing code in Tracker

        This is used by the import-time validator, to allow working-around gnarly
        import-time side-effects that might not manifest during normal test execution
        but may interfere with validation.
        """
        return None

    def record_dynamic(self) -> bool:
        """whether to track dynamic imports"""
        return False

    def implicit_anchor_aggregation(self) -> bool:
        return False

    def dynamic_anchors(self) -> Optional[Mapping[str, AbstractSet[str]]]:
        return None

    def dynamic_ignores(self) -> Optional[Mapping[str, AbstractSet[str]]]:
        return None

    def tracker_log(self) -> Optional[str]:
        """
        :return: an optional path to a file in which to store logs for Tracker
        """
        return None


class ValidatorMixin(ABC):
    """
    Extra API surface for use by validator.py
    """

    @abstractmethod
    def test_folders(self) -> Mapping[str, str]:
        """
        returns a list of filepaths containing test files

        These paths may be among the source_roots, or nested arbitrarily deep under
        any source_root
        """
        ...

    def is_test_file(self, name: str) -> bool:
        """
        Checks whether a given file name is expected to contain test code

        The default implementation reflects the default discovery rules from pytest:
            test_*.py and *_test.py are matched
        """
        # https://docs.pytest.org/en/latest/explanation/goodpractices.html#test-discovery
        # NB: can be overridden via config, hence this being part of the hook API surface
        return (name.startswith("test_") and name.endswith(".py")) or name.endswith(
            "_test.py"
        )

    def should_capture_stdout(self) -> bool:
        """whether to capture stdout during import-time validation runs"""
        return True

    def should_capture_stderr(self) -> bool:
        """whether to capture stderr during import-time validation runs"""
        return True

    def before_folder(self, fs: str, py: str) -> None:
        """
        callback invoked by import-time validator before validating each
        entry in test_folders

        This is only called for the top-level paths, not for each subfolder.
        """
        pass

    def after_folder(self, fs: str, py: str) -> None:
        """
        callback invoked by import-time validator after validating each
        entry in test_folders

        This is only called for the top-level paths, not for each subfolder.
        """
        pass

    def before_file(
        self,
        # sigh, mypy is being silly about generics on newer python versions...
        dent: os.DirEntry,  # type: ignore
        import_prefix: str,
    ) -> None:
        """
        callback invoked by import-time validator before validating each
        python test file encountered under a test_folder
        """
        pass

    def after_file(
        self,
        # sigh, mypy is being silly about generics on newer python versions...
        dent: os.DirEntry,  # type: ignore
        import_prefix: str,
    ) -> None:
        """
        callback invoked by import-time validator after validating each
        python test file encountered under a test_folder
        """
        pass


class PluginHook(BaseHook, TrackerMixin, metaclass=ABCMeta):
    """
    Full API used by pytest plugin
    """

    def always_run(self) -> AbstractSet[str]:
        """
        returns a set of test files, or individual test cases, that should
        never be de-selected, regardless of modified files and the import
        graph data, and should be excluded from test-time import validation.

        This is intended to exclude particularly gnarly files from test
        selection and test-time import validation. For instance, tests
        who might perform dynamic import based on data, or environment state
        that are impractical to encode into the import graph

        NB: this does *not* affect the import-time validator
        """
        return frozenset()

    def filter_irrelevant_files(self, files: Set[str]) -> Set[str]:
        """
        given a set of files, filter out those that are deemed irrelevant for
        testing purposes.

        By default prunepytest operates very conservatively, and will disable
        test pruning if the set of modified files includes files outside of the
        Python import graph.

        Typically, documentation and other files that are neither code, nor data
        used by the code, can be ignored for the the purpose of test selection.
        However what files are safe to ignore can vary widely depending between
        projects, so the default implementation is a no-op, to prioritize safety
        over maximum test pruning. A custom implementation allows more commits to
        leverage test pruning
        """
        return files


class ValidatorHook(PluginHook, ValidatorMixin, metaclass=ABCMeta):
    """
    Full API used by import-time validator
    """

    pass


class DefaultHook(ValidatorHook):
    """
    A default Hook implementation, that supports the full API required for
    the pytest plugin and the pre-test validator, based on a handful of
    static values.

    This is meant to provide sensible defaults based on prevalent Python
    conventions, and best-effort parsing of common configuration files,
    such as pyproject.toml

    It can be used as a base class for custom Hook implementations where
    most of the default behaviors are fine, and a only few settings need
    tweaking.
    """

    __slots__ = ("global_ns", "local_ns", "src_roots", "tst_dirs", "tst_file_pattern")

    def __init__(
        self,
        global_ns: AbstractSet[str],
        local_ns: AbstractSet[str],
        src_roots: Mapping[str, str],
        tst_dirs: Mapping[str, str],
        tst_file_pattern: Optional[str] = None,
    ):
        self.local_ns = local_ns
        self.global_ns = global_ns
        self.src_roots = src_roots
        self.tst_dirs = tst_dirs
        self.tst_file_pattern = tst_file_pattern

    def global_namespaces(self) -> AbstractSet[str]:
        return self.global_ns

    def local_namespaces(self) -> AbstractSet[str]:
        return self.local_ns

    def source_roots(self) -> Mapping[str, str]:
        return self.src_roots

    def test_folders(self) -> Mapping[str, str]:
        return self.tst_dirs

    def is_test_file(self, name: str) -> bool:
        if self.tst_file_pattern:
            return fnmatch(name, self.tst_file_pattern)
        return super().is_test_file(name)
