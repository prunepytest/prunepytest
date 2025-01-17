# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

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
                stderr=subprocess.STDOUT,
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
                    stderr=subprocess.STDOUT,
                )
                .decode("utf-8")
                .rstrip()
            )
            == 0
        )

    def commit_id(self, ref: str = "HEAD") -> str:
        return (
            subprocess.check_output(
                ["git", "rev-parse", ref],
                stdin=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            .decode("utf-8")
            .rstrip()
        )

    def recent_commits(self, n: int) -> List[str]:
        return [
            commit_line.partition(" ")[0]
            for commit_line in subprocess.check_output(
                ["git", "log", "--oneline", "-n", str(n)]
            )
            .decode("utf-8")
            .splitlines()
        ]

    def list_remotes(self) -> List[str]:
        return (
            subprocess.check_output(
                ["git", "remote"],
                stdin=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            .decode("utf-8")
            .rstrip()
            .split()
        )

    def fork_point(
        self, commit_id: str = "HEAD", from_ref: Optional[str] = None
    ) -> Optional[str]:
        try:
            if from_ref is None:
                remotes = self.list_remotes()
                candidates = {}
                for r in remotes:
                    for cand in ("master", "main"):
                        try:
                            ref = f"{r}/{cand}"
                            commit_id = self.commit_id(ref=ref)
                            candidates[ref] = cand
                        except subprocess.CalledProcessError:
                            continue
                if "origin/master" in candidates:
                    from_ref = candidates["origin/master"]
                elif "origin/main" in candidates:
                    from_ref = candidates["origin/main"]
                elif len(candidates) > 0:
                    from_ref = next(iter(candidates.keys()))
                else:
                    print("failed to infer a viable fork point")
                    return None

            return (
                subprocess.check_output(
                    [
                        "git",
                        "merge-base",
                        *(["--fork-point", from_ref] if from_ref else []),
                        commit_id,
                    ],
                    stdin=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
                .decode("utf-8")
                .rstrip()
            )
        except subprocess.CalledProcessError:
            return None

    def dirty_files(self) -> List[str]:
        # NB: this *does* include untracked files
        return list(
            itertools.chain.from_iterable(
                # remove status letters, strip whitespaces, and split to catch both sides of renames
                status[2:].strip().split()
                for status in subprocess.check_output(
                    ["git", "status", "--porcelain=v1"],
                    stdin=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
                .decode("utf-8")
                .splitlines()
            )
        )

    def _parents(self, commit_id: str) -> List[str]:
        return (
            subprocess.check_output(
                [
                    "git",
                    "show",
                    "-s",
                    "--pretty=%P",
                    commit_id,
                ],
                stdin=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            .decode("utf-8")
            .split()
        )

    def _merge_base(self, commits: List[str]) -> str:
        return (
            subprocess.check_output(
                [
                    "git",
                    "merge-base",
                    *commits,
                ],
                stdin=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
            .decode("utf-8")
            .rstrip()
        )

    def modified_files(
        self, commit_id: str = "HEAD", base_commit: Optional[str] = None
    ) -> List[str]:
        if not base_commit:
            parents = self._parents(commit_id)
            if len(parents) > 1:
                # merge commit, set the merge base of all parents as the base commit
                base_commit = self._merge_base(parents)

        return list(
            itertools.chain.from_iterable(
                # remove status, strip whitespaces, and split to catch both sides of renames
                status.split()[1:]
                for status in subprocess.check_output(
                    [
                        "git",
                        "show",
                        "--pretty=",
                        "--name-status",
                        f"{base_commit}..{commit_id}" if base_commit else commit_id,
                    ],
                    stdin=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                )
                .decode("utf-8")
                .splitlines()
                if status[0] not in {"?", "!"}
            )
        )
