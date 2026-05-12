from __future__ import annotations

import json
from pathlib import Path

import pytest

import folder_models
from folder_models import (
    QUARANTINE_DIRNAME,
    ManifestCompatibilityError,
    QuarantineStatus,
    load_manifest,
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
