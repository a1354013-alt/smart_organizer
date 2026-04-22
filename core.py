"""
Core public API (facade).

The legacy `core.py` grew large over time (OCR/PDF/video/deps/classification).
It is split into focused modules while keeping the same import surface for the app,
services, storage, and tests.
"""

from core_classification import DOCUMENT_TAGS, PHOTO_TAGS, VIDEO_KEYWORD_RULES, VIDEO_TAGS
from core_processor import FileProcessor
from core_utils import FileUtils

__all__ = [
    "FileUtils",
    "FileProcessor",
    "DOCUMENT_TAGS",
    "PHOTO_TAGS",
    "VIDEO_TAGS",
    "VIDEO_KEYWORD_RULES",
]

