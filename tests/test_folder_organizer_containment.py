from __future__ import annotations

from pathlib import Path

import pytest

from folder_organizer import FolderOrganizer
from folder_service import preview_selected_actions, scan_folder


def test_quarantine_rejects_source_outside_scan_root(tmp_path: Path):
    scan_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    outside_file = tmp_path / "outside.txt"
    scan_root.mkdir()
    quarantine_root.mkdir()
    outside_file.write_text("outside", encoding="utf-8")

    organizer = FolderOrganizer(scan_root, quarantine_root)
    result = organizer.quarantine_file(outside_file, "outside.txt")

    assert result.success is False
    assert result.error == "source path escapes scan root"
    assert outside_file.exists()


def test_quarantine_rejects_target_escape_with_parent_segments(tmp_path: Path):
    scan_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    source = scan_root / "nested" / "doc.txt"
    source.parent.mkdir(parents=True)
    quarantine_root.mkdir()
    source.write_text("data", encoding="utf-8")

    organizer = FolderOrganizer(scan_root, quarantine_root)
    result = organizer.quarantine_file(source, "../escape.txt")

    assert result.success is False
    assert result.error == "quarantine target escapes quarantine root"
    assert source.exists()


def test_restore_rejects_source_outside_quarantine_root(tmp_path: Path):
    scan_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    outside_source = tmp_path / "outside.txt"
    scan_root.mkdir()
    quarantine_root.mkdir()
    outside_source.write_text("outside", encoding="utf-8")

    organizer = FolderOrganizer(scan_root, quarantine_root)
    result = organizer.restore_file(outside_source, "restored.txt")

    assert result.success is False
    assert result.error == "restore source escapes quarantine root"
    assert outside_source.exists()


def test_restore_rejects_target_outside_scan_root(tmp_path: Path):
    scan_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    quarantined = quarantine_root / "doc.txt"
    scan_root.mkdir()
    quarantine_root.mkdir()
    quarantined.write_text("data", encoding="utf-8")

    organizer = FolderOrganizer(scan_root, quarantine_root)
    result = organizer.restore_file(quarantined, "../escape.txt")

    assert result.success is False
    assert result.error == "restore target escapes scan root"
    assert quarantined.exists()


def test_quarantine_and_restore_round_trip(tmp_path: Path):
    scan_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    source = scan_root / "nested" / "doc.txt"
    restored_target = Path("nested") / "doc.txt"
    scan_root.mkdir()
    quarantine_root.mkdir()
    source.parent.mkdir(parents=True)
    source.write_text("payload", encoding="utf-8")

    organizer = FolderOrganizer(scan_root, quarantine_root)

    quarantine_result = organizer.quarantine_file(source, "nested/doc.txt")
    assert quarantine_result.success is True
    assert source.exists() is False
    quarantined_path = quarantine_root / "nested" / "doc.txt"
    assert quarantined_path.exists()

    restore_result = organizer.restore_file(quarantined_path, restored_target)
    assert restore_result.success is True
    assert quarantined_path.exists() is False
    assert source.exists()
    assert source.read_text(encoding="utf-8") == "payload"


def test_low_level_quarantine_does_not_overwrite_existing_target(tmp_path: Path):
    scan_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    source = scan_root / "doc.txt"
    existing = quarantine_root / "doc.txt"
    scan_root.mkdir()
    quarantine_root.mkdir()
    source.write_text("new payload", encoding="utf-8")
    existing.write_text("existing payload", encoding="utf-8")

    organizer = FolderOrganizer(scan_root, quarantine_root)
    result = organizer.quarantine_file(source, "doc.txt")

    assert result.success is True
    assert result.target == str(quarantine_root / "doc__1.txt")
    assert existing.read_text(encoding="utf-8") == "existing payload"
    assert (quarantine_root / "doc__1.txt").read_text(encoding="utf-8") == "new payload"


def test_low_level_restore_does_not_overwrite_existing_target(tmp_path: Path):
    scan_root = tmp_path / "scan"
    quarantine_root = tmp_path / "quarantine"
    existing = scan_root / "doc.txt"
    quarantined = quarantine_root / "doc.txt"
    scan_root.mkdir()
    quarantine_root.mkdir()
    existing.write_text("existing payload", encoding="utf-8")
    quarantined.write_text("restored payload", encoding="utf-8")

    organizer = FolderOrganizer(scan_root, quarantine_root)
    result = organizer.restore_file(quarantined, "doc.txt")

    assert result.success is True
    assert result.target == str(scan_root / "doc__1.txt")
    assert existing.read_text(encoding="utf-8") == "existing payload"
    assert (scan_root / "doc__1.txt").read_text(encoding="utf-8") == "restored payload"


def test_scan_folder_skips_symlink_targets_for_safety(tmp_path: Path):
    inside = tmp_path / "inside.txt"
    outside_root = tmp_path.parent / f"{tmp_path.name}_outside"
    outside_root.mkdir(exist_ok=True)
    outside = outside_root / "outside.txt"
    symlink_path = tmp_path / "link.txt"
    inside.write_text("inside", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    try:
        symlink_path.symlink_to(outside)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    scan = scan_folder(str(tmp_path), recursive=False, max_files=20, stale_days=0, large_file_bytes=10)
    records = {row["path"]: row for row in scan["records"]}

    assert str(symlink_path) in records
    assert records[str(symlink_path)]["is_symlink"] is True
    assert records[str(symlink_path)]["recommendation"] == "Do not touch"

    preview = preview_selected_actions(scan, [str(symlink_path)])
    row = preview["results"][0]
    assert row["status"] == "SKIPPED"
    assert "symbolic link" in str(row["error_message"]).lower()
    assert outside.exists()
