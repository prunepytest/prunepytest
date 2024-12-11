# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

from typing import Optional

from . import VCS


def detect_vcs() -> Optional[VCS]:
    try:
        from .git import Git

        g = Git()
        g.repo_root()
        return g
    except Exception:
        pass

    # TODO: support more than just git...

    return None
