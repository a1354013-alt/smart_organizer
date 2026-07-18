from __future__ import annotations

import ctypes
import os
from pathlib import Path

import pytest

from path_utils import canonical_path_key, paths_refer_to_same_location


def _short_path(path: Path) -> str | None:
    if os.name != "nt":
        return None
    kernel32 = getattr(getattr(ctypes, "windll", None), "kernel32", None)
    if kernel32 is None:
        return None
    api = getattr(kernel32, "GetShortPathNameW", None)
    if api is None:
        return None
    required = api(str(path), None, 0)
    if required <= 0:
        return None
    buffer = ctypes.create_unicode_buffer(required)
    result = api(str(path), buffer, required)
    if result <= 0:
        return None
    short_value = buffer.value
    if not short_value or short_value == str(path):
        return None
    return short_value


def test_canonical_path_key_handles_relative_and_slash_aliases(tmp_path: Path):
    target = tmp_path / "folder" / "sample file.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("payload", encoding="utf-8")

    dotted = target.parent / "." / target.name
    slashed = str(target).replace("\\", "/")

    assert canonical_path_key(target) == canonical_path_key(dotted)
    assert canonical_path_key(target) == canonical_path_key(slashed)
    assert paths_refer_to_same_location(target, dotted)


def test_canonical_path_key_handles_unicode_and_spaces(tmp_path: Path):
    target = tmp_path / "資料 夾" / "測試 文件.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("payload", encoding="utf-8")

    assert canonical_path_key(target)
    assert paths_refer_to_same_location(target, str(target))


def test_paths_refer_to_same_location_uses_existing_samefile(tmp_path: Path):
    target = tmp_path / "same.txt"
    target.write_text("payload", encoding="utf-8")

    assert paths_refer_to_same_location(target, target)


def test_canonical_path_key_falls_back_for_nonexistent_paths(tmp_path: Path):
    missing = tmp_path / "missing" / ".." / "missing" / "file.txt"
    normalized = tmp_path / "missing" / "file.txt"

    assert canonical_path_key(missing) == canonical_path_key(normalized)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path alias behavior")
def test_canonical_path_key_matches_windows_short_and_long_paths(tmp_path: Path):
    target = tmp_path / "folder with spaces" / "short-name.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("payload", encoding="utf-8")

    short_value = _short_path(target)
    if short_value is None:
        pytest.skip("8.3 short path alias is unavailable on this Windows runner")

    assert canonical_path_key(target) == canonical_path_key(short_value)
    assert paths_refer_to_same_location(target, short_value)
