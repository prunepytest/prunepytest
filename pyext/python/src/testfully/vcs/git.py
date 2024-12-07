import itertools
import subprocess
from typing import List, Optional

from . import VCS


class Git(VCS):
    def repo_root(self) -> str:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                stdin=subprocess.DEVNULL,
            )
            .decode("utf-8")
            .rstrip()
        )

    def is_repo_clean(self) -> bool:
        return (
            len(
                subprocess.check_output(
                    ["git", "status", "--porcelain=v1"],
                    stdin=subprocess.DEVNULL,
                )
                .decode("utf-8")
                .rstrip()
            )
            == 0
        )

    def commit_id(self) -> str:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                stdin=subprocess.DEVNULL,
            )
            .decode("utf-8")
            .rstrip()
        )

    def dirty_files(self) -> List[str]:
        # NB: this *does* include untracked files
        return list(
            itertools.chain.from_iterable(
                # remove status letters, strip whitespaces, and split to catch both sides of renames
                status[2:].strip().split()
                for status in subprocess.check_output(
                    ["git", "status", "--porcelain=v1"],
                    stdin=subprocess.DEVNULL,
                )
                .decode("utf-8")
                .splitlines()
            )
        )

    def modified_files(
        self, commit_id: str = "HEAD", base_commit: Optional[str] = None
    ) -> List[str]:
        return list(
            itertools.chain.from_iterable(
                # remove status letters, strip whitespaces, and split to catch both sides of renames
                status[2:].strip().split()
                for status in subprocess.check_output(
                    [
                        "git",
                        "show",
                        "--pretty=",
                        "--name-status",
                        f"{base_commit}..{commit_id}" if base_commit else commit_id,
                    ],
                    stdin=subprocess.DEVNULL,
                )
                .decode("utf-8")
                .splitlines()
                if status[0:2] not in {"??", "!!"}
            )
        )
