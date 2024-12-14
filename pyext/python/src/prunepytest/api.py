# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

import os
from abc import ABC, abstractmethod, ABCMeta
from fnmatch import fnmatch

from typing import AbstractSet, Any, Mapping, Optional, Sequence, Tuple


class BaseHook(ABC):
    """
    API surface to create a ModuleGraph object
    """

    def setup(self) -> None:
        pass

    @abstractmethod
    def global_namespaces(self) -> AbstractSet[str]: ...

    @abstractmethod
    def local_namespaces(self) -> AbstractSet[str]: ...

    @abstractmethod
    def source_roots(self) -> Mapping[str, str]: ...

    def include_typechecking(self) -> bool:
        return False

    def external_imports(self) -> AbstractSet[str]:
        return frozenset()

    def dynamic_dependencies(self) -> Mapping[str, AbstractSet[str]]:
        return {}

    def dynamic_dependencies_at_edges(
        self,
    ) -> Tuple[
        Sequence[Tuple[str, AbstractSet[str]]],
        Sequence[Tuple[str, Mapping[str, AbstractSet[str]]]],
    ]:
        return (), ()


class TrackerMixin:
    """
    API surface to configure a Tracker object
    """

    def import_patches(self) -> Optional[Mapping[str, Any]]:
        return None

    def record_dynamic(self) -> bool:
        return False

    def implicit_anchor_aggregation(self) -> bool:
        return False

    def dynamic_anchors(self) -> Optional[Mapping[str, AbstractSet[str]]]:
        return None

    def dynamic_ignores(self) -> Optional[Mapping[str, AbstractSet[str]]]:
        return None

    def tracker_log(self) -> Optional[str]:
        return None


class ValidatorMixin(ABC):
    """
    Extra API surface for use by validator.py
    """

    @abstractmethod
    def test_folders(self) -> Mapping[str, str]: ...

    def is_test_file(self, name: str) -> bool:
        # https://docs.pytest.org/en/latest/explanation/goodpractices.html#test-discovery
        # NB: can be overridden via config, hence this being part of the hook API surface
        return (name.startswith("test_") and name.endswith(".py")) or name.endswith(
            "_test.py"
        )

    def should_capture_stdout(self) -> bool:
        return True

    def should_capture_stderr(self) -> bool:
        return True

    def before_folder(self, fs: str, py: str) -> None:
        pass

    def after_folder(self, fs: str, py: str) -> None:
        pass

    def before_file(
        self,
        # sigh, mypy is being silly about generics on newer python versions...
        dent: os.DirEntry,  # type: ignore
        import_prefix: str,
    ) -> None:
        pass

    def after_file(
        self,
        # sigh, mypy is being silly about generics on newer python versions...
        dent: os.DirEntry,  # type: ignore
        import_prefix: str,
    ) -> None:
        pass


class PluginHook(BaseHook, TrackerMixin, metaclass=ABCMeta):
    """
    Full API used by pytest plugin
    """

    def always_run(self) -> AbstractSet[str]:
        return frozenset()


class ValidatorHook(PluginHook, ValidatorMixin, metaclass=ABCMeta):
    """
    Full API used by validator.py
    """

    pass


class ZeroConfHook(ValidatorHook):
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
