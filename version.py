"""
Single source of truth for Smart Organizer versioning.

Keep ALL version references (UI title, README badge/title, release zip naming, changelog)
in sync with this module. Tests enforce consistency to prevent drift.
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "APP_TITLE"]

# Semantic version of the project (runtime/demo release uses this string in its zip name)
__version__ = "2.8.0"

# User-facing app name/title
APP_NAME = "智慧檔案整理助理"
APP_TITLE = f"{APP_NAME} (v{__version__})"
