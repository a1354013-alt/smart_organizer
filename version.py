"""
Single source of truth for Smart Organizer versioning.

Keep UI titles, release artifacts, and docs aligned with this module.
"""

from __future__ import annotations

__all__ = ["__version__", "APP_NAME", "APP_TITLE"]

__version__ = "2.8.5rc5"

APP_NAME = "Smart Organizer"
APP_TITLE = f"{APP_NAME} (v{__version__})"
