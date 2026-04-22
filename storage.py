"""
Storage public API (facade).

Historically this project used a single large `storage.py`. To reduce maintenance risk,
the implementation is split into focused modules while keeping the original imports
stable for the app, services, tests, and the official runtime/demo release zip.
"""

from storage_base import CURRENT_SCHEMA_VERSION, MAX_UPLOAD_BYTES, SearchContentError, _log_context
from storage_manager import StorageManager

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MAX_UPLOAD_BYTES",
    "SearchContentError",
    "StorageManager",
    "_log_context",
]

