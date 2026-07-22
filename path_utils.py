from __future__ import annotations

import ctypes
import os

PathLikeStr = str | os.PathLike[str]


def _existing_samefile(left: PathLikeStr, right: PathLikeStr) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return False


def _get_long_path_name(path: str) -> str:
    if os.name != "nt":
        return path
    kernel32 = getattr(ctypes, "windll", None)
    if kernel32 is None:
        return path
    get_long_path_name = getattr(kernel32.kernel32, "GetLongPathNameW", None)
    if get_long_path_name is None:
        return path
    required = get_long_path_name(path, None, 0)
    if required <= 0:
        return path
    buffer = ctypes.create_unicode_buffer(required)
    result = get_long_path_name(path, buffer, required)
    if result <= 0:
        return path
    return buffer.value or path


def canonical_path(path: PathLikeStr) -> str:
    raw = os.fspath(path)
    absolute = os.path.abspath(raw)
    real = os.path.realpath(absolute)
    normalized = os.path.normpath(real)
    if os.name == "nt":
        normalized = _get_long_path_name(normalized)
    return normalized


def canonical_path_key(path: PathLikeStr) -> str:
    return os.path.normcase(canonical_path(path))


def paths_refer_to_same_location(left: PathLikeStr, right: PathLikeStr) -> bool:
    if _existing_samefile(left, right):
        return True
    return canonical_path_key(left) == canonical_path_key(right)


def canonical_path_set(paths: list[str]) -> set[str]:
    return {canonical_path_key(path) for path in paths}
