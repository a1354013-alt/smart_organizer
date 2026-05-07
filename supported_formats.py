from __future__ import annotations

SUPPORTED_UPLOAD_EXTENSIONS: tuple[str, ...] = (
    "pdf",
    "jpg",
    "jpeg",
    "png",
    "mp4",
    "mov",
    "mkv",
    "avi",
    "webm",
    "m4v",
)

SUPPORTED_UPLOAD_SUFFIXES: tuple[str, ...] = tuple(f".{ext}" for ext in SUPPORTED_UPLOAD_EXTENSIONS)
SUPPORTED_VIDEO_EXTENSIONS: tuple[str, ...] = ("mp4", "mov", "mkv", "avi", "webm", "m4v")
SUPPORTED_VIDEO_SUFFIXES: tuple[str, ...] = tuple(f".{ext}" for ext in SUPPORTED_VIDEO_EXTENSIONS)


def supported_upload_extensions_label() -> str:
    return ", ".join(SUPPORTED_UPLOAD_EXTENSIONS)
