# SPDX-FileCopyrightText: © 2024 Hugues Bruant <hugues.bruant@gmail.com>

"""
This module is a public API: it is expected that compatibility will be
preserved across minor and patch releases.
"""

# NB: explicit re-export
from ._prunepytest import ModuleGraph as ModuleGraph  # noqa: F401
