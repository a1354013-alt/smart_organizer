from __future__ import annotations

from pathlib import Path

import pytest

import scripts.validate_dependency_locks as validate_dependency_locks


def test_validate_dependency_locks_static_mode_skips_regeneration(monkeypatch: pytest.MonkeyPatch):
    called = False

    def fail_compile(input_path: Path, output_path: Path) -> None:
        nonlocal called
        del input_path, output_path
        called = True
        raise AssertionError("static mode should not regenerate lock files")

    monkeypatch.setattr(validate_dependency_locks, "_compile_lock", fail_compile)

    validate_dependency_locks.validate_locks(mode="static")

    assert called is False


def test_validate_dependency_locks_regenerate_mode_detects_stale_lock(monkeypatch: pytest.MonkeyPatch):
    def fake_compile(input_path: Path, output_path: Path) -> None:
        output_path.write_text(
            "# generated\npackage==0.0.0\n",
            encoding="utf-8",
        )

    monkeypatch.setattr(validate_dependency_locks, "_compile_lock", fake_compile)

    with pytest.raises(RuntimeError, match="requirements.lock.txt is stale"):
        validate_dependency_locks.validate_locks(mode="regenerate")


def test_validate_dependency_locks_parse_args_supports_explicit_modes():
    args = validate_dependency_locks.parse_args(["--mode", "static"])

    assert args.mode == "static"
    assert args.no_regenerate_check is False
