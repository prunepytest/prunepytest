from abc import ABC, abstractmethod, ABCMeta

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
    def package_map(self) -> Mapping[str, str]: ...

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

    def before_folder(self, base: str, sub: str) -> None:
        pass

    def after_folder(self, base: str, sub: str) -> None:
        pass


class PluginHook(BaseHook, TrackerMixin, metaclass=ABCMeta):
    """
    Full API used by pytest plugin
    """

    pass


class ValidatorHook(PluginHook, ValidatorMixin, metaclass=ABCMeta):
    """
    Full API used by validator.py
    """

    pass


class ZeroConfHook(ValidatorHook):
    __slots__ = ("global_ns", "local_ns", "pkg_map", "tst_dirs")

    def __init__(
        self,
        global_ns: AbstractSet[str],
        local_ns: AbstractSet[str],
        pkg_map: Mapping[str, str],
        tst_dirs: Mapping[str, str],
    ):
        self.local_ns = local_ns
        self.global_ns = global_ns
        self.pkg_map = pkg_map
        self.tst_dirs = tst_dirs

    def global_namespaces(self) -> AbstractSet[str]:
        return self.global_ns

    def local_namespaces(self) -> AbstractSet[str]:
        return self.local_ns

    def package_map(self) -> Mapping[str, str]:
        return self.pkg_map

    def test_folders(self) -> Mapping[str, str]:
        return self.tst_dirs
