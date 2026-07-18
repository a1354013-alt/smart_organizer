from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import folder_models
from folder_models import (
    QUARANTINE_DIRNAME,
    ManifestCompatibilityError,
    QuarantineStatus,
    describe_manifest_lock,
    load_manifest,
    quarantine_manifest_guard,
    quarantine_manifest_lock_path,
    quarantine_manifest_path,
    save_manifest,
)
from folder_organizer import (
    recover_quarantine_manifest,
    restore_quarantined_items,
    run_folder_organizer,
    scan_local_folder,
)


def test_save_manifest_atomic_success(tmp_path: Path):
    save_manifest(
        tmp_path,
        {
            "items": [
                {
                    "original_path": str(tmp_path / "a.txt"),
                    "quarantine_path": str(tmp_path / QUARANTINE_DIRNAME / "a.txt"),
                    "status": QuarantineStatus.QUARANTINED.value,
                }
            ]
        },
    )

    manifest_path = quarantine_manifest_path(tmp_path)
    assert manifest_path.exists()
    assert not manifest_path.with_name("manifest.json.tmp").exists()
    assert load_manifest(tmp_path)["items"][0]["status"] == QuarantineStatus.QUARANTINED.value


def test_save_manifest_failure_preserves_existing_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    save_manifest(tmp_path, {"items": []})
    manifest_path = quarantine_manifest_path(tmp_path)
    original = manifest_path.read_text(encoding="utf-8")

    def fail_replace(src: object, dst: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(folder_models.os, "replace", fail_replace)

    with pytest.raises(ManifestCompatibilityError):
        save_manifest(
            tmp_path,
            {
                "items": [
                    {
                        "original_path": str(tmp_path / "a.txt"),
                        "quarantine_path": str(tmp_path / QUARANTINE_DIRNAME / "a.txt"),
                        "status": QuarantineStatus.QUARANTINED.value,
                    }
                ]
            },
        )

    assert manifest_path.read_text(encoding="utf-8") == original
    assert not manifest_path.with_name("manifest.json.tmp").exists()


def test_invalid_manifest_is_reported_safely(tmp_path: Path):
    manifest_path = quarantine_manifest_path(tmp_path)
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ManifestCompatibilityError, match="Manifest is not valid JSON"):
        load_manifest(tmp_path)


def test_restore_does_not_delete_when_manifest_is_invalid(tmp_path: Path):
    quarantine_root = tmp_path / QUARANTINE_DIRNAME
    quarantine_root.mkdir()
    original = tmp_path / "original.txt"
    original.write_text("new user file", encoding="utf-8")
    quarantined = quarantine_root / "original.txt"
    quarantined.write_text("old file", encoding="utf-8")
    quarantine_manifest_path(tmp_path).write_text("{broken", encoding="utf-8")

    with pytest.raises(ManifestCompatibilityError):
        restore_quarantined_items(str(tmp_path), [str(quarantined)])

    assert original.read_text(encoding="utf-8") == "new user file"
    assert quarantined.read_text(encoding="utf-8") == "old file"


def test_duplicate_quarantine_is_rejected(tmp_path: Path):
    target = tmp_path / "old.txt"
    target.write_text("old", encoding="utf-8")
    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=0, large_file_bytes=1)
    first = run_folder_organizer(scan, [str(target)], dry_run=False)
    assert first["summary"]["success"] == 1

    forged_scan = dict(scan)
    forged_scan["records"] = [
        {
            "path": str(target),
            "candidate_reasons": ["forged duplicate"],
            "size_bytes": 3,
            "mtime": "2026-05-12T00:00:00+00:00",
        }
    ]
    second = run_folder_organizer(forged_scan, [str(target)], dry_run=False)
    assert second["summary"]["failed"] == 1
    assert "already has an active quarantine" in second["results"][0]["error_message"]


def test_recover_moving_manifest_status(tmp_path: Path):
    quarantine_root = tmp_path / QUARANTINE_DIRNAME
    quarantine_root.mkdir()
    quarantined = quarantine_root / "old.txt"
    quarantined.write_text("moved", encoding="utf-8")
    manifest = {
        "items": [
            {
                "original_path": str(tmp_path / "old.txt"),
                "quarantine_path": str(quarantined),
                "status": QuarantineStatus.MOVING.value,
            }
        ]
    }
    quarantine_manifest_path(tmp_path).write_text(json.dumps(manifest), encoding="utf-8")

    recovered = recover_quarantine_manifest(str(tmp_path))
    assert recovered["items"][0]["status"] == QuarantineStatus.QUARANTINED.value


def test_scan_local_folder_warns_and_continues_when_manifest_is_invalid(tmp_path: Path):
    candidate = tmp_path / "old.log"
    candidate.write_text("stale", encoding="utf-8")
    quarantine_root = tmp_path / QUARANTINE_DIRNAME
    quarantine_root.mkdir()
    quarantine_manifest_path(tmp_path).write_text("{broken", encoding="utf-8")

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=0, large_file_bytes=1024)

    assert scan["stats"]["scanned_files"] == 1
    assert scan["stats"]["quarantine_files"] == 0
    assert any("Quarantine manifest warning" in message for message in scan["errors"])
    assert quarantine_manifest_path(tmp_path).read_text(encoding="utf-8") == "{broken"


def test_manifest_guard_blocks_until_lock_is_released(tmp_path: Path):
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    observed: list[float] = []

    def worker() -> None:
        with quarantine_manifest_guard(tmp_path):
            entered.set()
            release.wait(timeout=2)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    assert entered.wait(timeout=2)

    def saver() -> None:
        started = time.perf_counter()
        save_manifest(tmp_path, {"items": []})
        observed.append(time.perf_counter() - started)
        completed.set()

    saver_thread = threading.Thread(target=saver, daemon=True)
    saver_thread.start()
    time.sleep(0.2)
    assert not completed.is_set()

    release.set()
    assert completed.wait(timeout=2)
    saver_thread.join(timeout=2)
    thread.join(timeout=2)
    assert observed and observed[0] >= 0.15
    assert not quarantine_manifest_lock_path(tmp_path).exists()


def test_manifest_guard_reports_stale_lock_file_clearly(tmp_path: Path):
    lock_path = quarantine_manifest_lock_path(tmp_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("stale", encoding="utf-8")

    with (
        pytest.raises(ManifestCompatibilityError, match="stale lock file"),
        quarantine_manifest_guard(tmp_path, timeout_seconds=0.1, poll_seconds=0.01),
    ):
        raise AssertionError("Expected stale lock acquisition to fail")

    assert lock_path.exists()


def test_manifest_guard_writes_lock_owner_metadata(tmp_path: Path):
    lock_path = quarantine_manifest_lock_path(tmp_path)
    with quarantine_manifest_guard(tmp_path):
        diagnostics = describe_manifest_lock(tmp_path)
        metadata = diagnostics["metadata"]

        assert lock_path.exists()
        assert isinstance(metadata, dict)
        assert metadata["pid"]
        assert metadata["hostname"]
        assert metadata["created_at"]
        assert "command" in metadata

    assert not lock_path.exists()


def test_manifest_guard_preserves_primary_error_when_lock_release_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    real_unlink = Path.unlink

    def failing_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self == quarantine_manifest_lock_path(tmp_path):
            raise OSError("release failed")
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(ValueError, match="primary failure"), quarantine_manifest_guard(tmp_path):
        raise ValueError("primary failure")

    assert "Failed to release manifest lock after primary error" in caplog.text


def test_manifest_guard_reports_release_error_without_primary_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    real_unlink = Path.unlink

    def failing_unlink(self: Path, *args: object, **kwargs: object) -> None:
        if self == quarantine_manifest_lock_path(tmp_path):
            raise OSError("release failed")
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(ManifestCompatibilityError, match="Failed to release manifest lock"), quarantine_manifest_guard(
        tmp_path
    ):
        pass


def test_manifest_guard_reentrant_alias_cleans_owner_map(tmp_path: Path):
    alias_root = tmp_path / "." / "subdir" / ".."

    with quarantine_manifest_guard(tmp_path), quarantine_manifest_guard(alias_root):
        assert folder_models._MANIFEST_LOCK_OWNERS
        assert quarantine_manifest_lock_path(tmp_path).exists()

    assert folder_models._MANIFEST_LOCK_OWNERS == {}
    assert not quarantine_manifest_lock_path(tmp_path).exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific path alias behavior")
def test_manifest_guard_case_only_alias_is_reentrant_on_windows(tmp_path: Path):
    case_alias = Path(str(tmp_path).swapcase())

    with quarantine_manifest_guard(tmp_path), quarantine_manifest_guard(case_alias):
        assert quarantine_manifest_lock_path(tmp_path).exists()

    assert folder_models._MANIFEST_LOCK_OWNERS == {}


def test_manifest_guard_blocks_other_process(tmp_path: Path):
    ready = tmp_path / "ready.txt"
    release = tmp_path / "release.txt"
    child_script = tmp_path / "hold_lock.py"
    child_script.write_text(
        "import sys, time\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[4])\n"
        "from folder_models import quarantine_manifest_guard\n"
        "root = Path(sys.argv[1])\n"
        "ready = Path(sys.argv[2])\n"
        "release = Path(sys.argv[3])\n"
        "with quarantine_manifest_guard(root):\n"
        "    ready.write_text('ready', encoding='utf-8')\n"
        "    deadline = time.time() + 10\n"
        "    while not release.exists() and time.time() < deadline:\n"
        "        time.sleep(0.05)\n",
        encoding="utf-8",
    )

    proc = subprocess.Popen(
        [sys.executable, str(child_script), str(tmp_path), str(ready), str(release), str(Path(__file__).resolve().parents[1])],
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    try:
        deadline = time.time() + 10
        while not ready.exists() and time.time() < deadline:
            time.sleep(0.05)
        assert ready.exists()

        with pytest.raises(
            ManifestCompatibilityError,
            match="Timed out waiting for manifest lock",
        ), quarantine_manifest_guard(tmp_path, timeout_seconds=0.1, poll_seconds=0.01):
            pass
    finally:
        release.write_text("release", encoding="utf-8")
        proc.wait(timeout=10)

    assert proc.returncode == 0
    assert folder_models._MANIFEST_LOCK_OWNERS == {}
