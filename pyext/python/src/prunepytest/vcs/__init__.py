# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

from abc import ABC, abstractmethod
from typing import List, Optional


class VCS(ABC):
    @abstractmethod
    def repo_root(self) -> str: ...

    @abstractmethod
    def commit_id(self) -> str: ...

    @abstractmethod
    def recent_commits(self, n: int) -> List[str]: ...

    @abstractmethod
    def is_repo_clean(self) -> bool: ...

    @abstractmethod
    def dirty_files(self) -> List[str]: ...

    @abstractmethod
    def modified_files(
        self, commit_id: str = "HEAD", base_commit: Optional[str] = None
    ) -> List[str]: ...
