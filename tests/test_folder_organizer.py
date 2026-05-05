from __future__ import annotations

from pathlib import Path

from ui_common import (
    export_folder_report_markdown,
    list_quarantine_items,
    restore_quarantined_items,
    run_folder_organizer,
    scan_local_folder,
)


def test_scan_local_folder_marks_stale_and_large_candidates(tmp_path: Path):
    stale_file = tmp_path / "old.bin"
    stale_file.write_bytes(b"0" * 4096)
    scan = scan_local_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1024,
    )
    stats = scan["stats"]
    assert isinstance(stats, dict)
    assert stats["scanned_files"] == 1
    assert stats["stale_candidates"] == 1
    assert stats["large_candidates"] == 1


def test_quarantine_move_restore_and_report(tmp_path: Path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4\n%%EOF\n")
    scan = scan_local_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )
    selected = [str(target)]

    preview = run_folder_organizer(scan, selected, dry_run=True)
    preview_summary = preview["summary"]
    assert isinstance(preview_summary, dict)
    assert preview_summary["skipped"] == 1

    moved = run_folder_organizer(scan, selected, dry_run=False)
    moved_summary = moved["summary"]
    assert isinstance(moved_summary, dict)
    assert moved_summary["success"] == 1
    assert not target.exists()

    quarantine_items = list_quarantine_items(str(tmp_path))
    assert len(quarantine_items) == 1

    restored = restore_quarantined_items(str(tmp_path), [str(quarantine_items[0]["quarantine_path"])])
    restored_summary = restored["summary"]
    assert isinstance(restored_summary, dict)
    assert restored_summary["success"] == 1
    assert target.exists()

    report = export_folder_report_markdown(scan, moved)
    assert "Smart Organizer Report" in report
    assert "report.pdf" in report
