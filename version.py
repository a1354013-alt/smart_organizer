"""
Single source of truth for Smart Organizer versioning.

Keep ALL version references (UI title, README title, release zip naming, docs)
in sync with this module. Tests enforce consistency to prevent drift.
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "APP_TITLE"]

__version__ = "2.8.4"

APP_NAME = "智慧檔案整理助理"
APP_TITLE = f"{APP_NAME} (v{__version__})"

