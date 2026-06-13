from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import cast

import folder_organizer
from folder_models import QUARANTINE_DIRNAME, ScanPathError
from folder_organizer import (
    SIMILAR_NAME_COMPARISON_LIMIT,
    list_quarantine_items,
    restore_quarantined_items,
    run_folder_organizer,
    scan_local_folder,
)
from folder_report import export_folder_report_csv, export_folder_report_markdown


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


def test_scan_local_folder_rejects_missing_root(tmp_path: Path):
    missing = tmp_path / "missing"

    try:
        scan_local_folder(str(missing), recursive=True, max_files=10, stale_days=0)
    except ScanPathError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("Expected missing scan root to raise ScanPathError")


def test_scan_local_folder_rejects_file_root(tmp_path: Path):
    not_dir = tmp_path / "single.txt"
    not_dir.write_text("hello", encoding="utf-8")

    try:
        scan_local_folder(str(not_dir), recursive=True, max_files=10, stale_days=0)
    except ScanPathError as exc:
        assert "not a directory" in str(exc)
    else:
        raise AssertionError("Expected non-directory scan root to raise ScanPathError")


def test_scan_local_folder_reports_permission_denied_without_stopping(monkeypatch, tmp_path: Path):
    readable = tmp_path / "good.txt"
    blocked = tmp_path / "blocked.txt"
    readable.write_text("good", encoding="utf-8")
    blocked.write_text("blocked", encoding="utf-8")
    original_stat = Path.stat

    def fake_stat(self: Path, *args, **kwargs):
        if self == blocked:
            raise PermissionError("blocked for test")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=10, stale_days=0)

    assert scan["stats"]["scanned_files"] == 1
    assert any("Permission denied" in message for message in scan["errors"])
    assert any(record["path"] == str(readable) for record in scan["records"])


def test_scan_local_folder_rejects_permission_denied_root(monkeypatch, tmp_path: Path):
    original_stat = Path.stat

    def fake_stat(self: Path, *args, **kwargs):
        if self == tmp_path:
            raise PermissionError("blocked root")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    try:
        scan_local_folder(str(tmp_path), recursive=True, max_files=10, stale_days=0)
    except ScanPathError as exc:
        assert "Permission denied" in str(exc)
    else:
        raise AssertionError("Expected permission denied scan root to raise ScanPathError")


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

    csv_payload = export_folder_report_csv(scan, moved)
    assert csv_payload.startswith(b"\xef\xbb\xbf")
    decoded = csv_payload.decode("utf-8-sig")
    rows = list(csv.DictReader(decoded.splitlines()))
    assert rows
    assert rows[0]["scan_path"] == str(tmp_path)
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["operation_id"] == moved["operation_id"]
    assert "duplicate_type" in rows[0]


def test_folder_dry_run_preserves_nested_quarantine_path_without_moving(tmp_path: Path):
    target = tmp_path / "sub" / "old.txt"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    scan = scan_local_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )

    preview = run_folder_organizer(scan, [str(target)], dry_run=True)

    rows = preview["results"]
    assert isinstance(rows, list)
    operation_id = cast(str, preview["operation_id"])
    expected = tmp_path / QUARANTINE_DIRNAME / operation_id / "sub" / "old.txt"
    assert preview["summary"]["skipped"] == 1
    assert rows[0]["new_path"] == str(expected)
    assert target.exists()
    assert not expected.exists()
    quarantine_root = tmp_path / QUARANTINE_DIRNAME
    assert not any(path.is_file() for path in quarantine_root.rglob("*"))


def test_folder_execute_uses_same_nested_relative_path_shape_as_dry_run(tmp_path: Path):
    target = tmp_path / "sub" / "old.txt"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    scan = scan_local_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )

    preview = run_folder_organizer(scan, [str(target)], dry_run=True)
    moved = run_folder_organizer(scan, [str(target)], dry_run=False)

    preview_row = preview["results"][0]
    moved_row = moved["results"][0]
    preview_operation_id = cast(str, preview["operation_id"])
    moved_operation_id = cast(str, moved["operation_id"])
    preview_relative = Path(str(preview_row["new_path"])).relative_to(
        tmp_path / QUARANTINE_DIRNAME / preview_operation_id
    )
    moved_relative = Path(str(moved_row["new_path"])).relative_to(
        tmp_path / QUARANTINE_DIRNAME / moved_operation_id
    )
    assert preview_relative == Path("sub") / "old.txt"
    assert moved_relative == preview_relative
    assert not target.exists()
    assert (tmp_path / QUARANTINE_DIRNAME / moved_operation_id / "sub" / "old.txt").exists()


def test_folder_restore_nested_file_from_quarantine(tmp_path: Path):
    target = tmp_path / "sub" / "old.txt"
    target.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    scan = scan_local_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )
    moved = run_folder_organizer(scan, [str(target)], dry_run=False)
    operation_id = cast(str, moved["operation_id"])
    quarantined_path = tmp_path / QUARANTINE_DIRNAME / operation_id / "sub" / "old.txt"

    restored = restore_quarantined_items(str(tmp_path), [str(quarantined_path)])

    assert restored["summary"]["success"] == 1
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "old"
    assert not quarantined_path.exists()
    assert list_quarantine_items(str(tmp_path)) == []


def test_same_named_nested_files_keep_distinct_quarantine_targets(tmp_path: Path):
    first = tmp_path / "a" / "file.txt"
    second = tmp_path / "b" / "file.txt"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("a", encoding="utf-8")
    second.write_text("b", encoding="utf-8")
    scan = scan_local_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )

    preview = run_folder_organizer(scan, [str(first), str(second)], dry_run=True)
    moved = run_folder_organizer(scan, [str(first), str(second)], dry_run=False)

    preview_paths = {Path(str(row["new_path"])) for row in preview["results"]}
    operation_id = cast(str, moved["operation_id"])
    preview_operation_id = cast(str, preview["operation_id"])
    assert len(preview_paths) == 2
    assert tmp_path / QUARANTINE_DIRNAME / preview_operation_id / "a" / "file.txt" in preview_paths
    assert tmp_path / QUARANTINE_DIRNAME / preview_operation_id / "b" / "file.txt" in preview_paths
    assert (tmp_path / QUARANTINE_DIRNAME / operation_id / "a" / "file.txt").read_text(
        encoding="utf-8"
    ) == "a"
    assert (tmp_path / QUARANTINE_DIRNAME / operation_id / "b" / "file.txt").read_text(
        encoding="utf-8"
    ) == "b"


def test_restore_quarantined_items_does_not_overwrite_existing_file(tmp_path: Path):
    target = tmp_path / "report.pdf"
    target.write_bytes(b"%PDF-1.4\n%%EOF\n")
    scan = scan_local_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )
    moved = run_folder_organizer(scan, [str(target)], dry_run=False)
    assert moved["summary"]["success"] == 1
    quarantine_item = list_quarantine_items(str(tmp_path))[0]

    target.write_text("new user file", encoding="utf-8")
    restored = restore_quarantined_items(str(tmp_path), [str(quarantine_item["quarantine_path"])])

    rows = restored["results"]
    assert isinstance(rows, list)
    assert restored["summary"]["success"] == 1
    assert target.read_text(encoding="utf-8") == "new user file"
    restored_path = Path(str(rows[0]["new_path"]))
    assert restored_path.name == "report__1.pdf"
    assert restored_path.exists()


def test_list_quarantine_items_accepts_legacy_manifest_shape(tmp_path: Path):
    quarantine_dir = tmp_path / QUARANTINE_DIRNAME
    quarantine_dir.mkdir(parents=True)
    manifest_path = quarantine_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "original_path": str(tmp_path / "legacy.txt"),
                        "new_path": str(quarantine_dir / "legacy.txt"),
                        "processed_at": "2026-05-05T00:00:00+00:00",
                        "file_size": 12,
                        "reason": "legacy",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    items = list_quarantine_items(str(tmp_path))
    assert len(items) == 1
    assert items[0]["quarantine_path"] == str(quarantine_dir / "legacy.txt")
    assert items[0]["status"] == "QUARANTINED"


def test_list_quarantine_items_raises_on_invalid_manifest_json(tmp_path: Path):
    quarantine_dir = tmp_path / QUARANTINE_DIRNAME
    quarantine_dir.mkdir(parents=True)
    manifest_path = quarantine_dir / "manifest.json"
    manifest_path.write_text("{not-json", encoding="utf-8")

    try:
        list_quarantine_items(str(tmp_path))
    except Exception as exc:
        assert "Manifest is not valid JSON" in str(exc)
    else:
        raise AssertionError("Expected manifest parsing to fail")


def test_run_folder_organizer_rejects_forged_record_outside_scan_root(tmp_path: Path):
    scan_root = tmp_path / "scan"
    outside_root = tmp_path / "outside"
    scan_root.mkdir()
    outside_root.mkdir()
    outside_file = outside_root / "escape.pdf"
    outside_file.write_bytes(b"%PDF-1.4\n%%EOF\n")

    forged_scan: dict[str, object] = {
        "path": str(scan_root),
        "records": [
            {
                "path": str(outside_file),
                "candidate_reasons": ["forged"],
                "size_bytes": outside_file.stat().st_size,
                "mtime": "2026-05-07T00:00:00+00:00",
            }
        ],
    }

    result = run_folder_organizer(forged_scan, [str(outside_file)], dry_run=False)
    summary = result["summary"]
    rows = result["results"]
    assert isinstance(summary, dict)
    assert isinstance(rows, list)
    operation_id = cast(str, result["operation_id"])
    assert summary["failed"] == 1
    assert rows[0]["status"] == "FAILED"
    assert "escapes scan root" in str(rows[0]["error_message"])
    assert outside_file.exists()
    assert not (scan_root / QUARANTINE_DIRNAME / operation_id / outside_file.name).exists()


def test_restore_quarantined_items_rejects_tampered_manifest_paths(tmp_path: Path):
    scan_root = tmp_path / "scan"
    outside_root = tmp_path / "outside"
    scan_root.mkdir()
    outside_root.mkdir()
    quarantine_root = scan_root / QUARANTINE_DIRNAME
    quarantine_root.mkdir()

    valid_quarantined = quarantine_root / "safe.pdf"
    valid_quarantined.write_bytes(b"%PDF-1.4\n%%EOF\n")
    outside_quarantined = outside_root / "escape.pdf"
    outside_quarantined.write_bytes(b"%PDF-1.4\n%%EOF\n")

    manifest_path = quarantine_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "original_path": str(outside_root / "restored-outside.pdf"),
                        "quarantine_path": str(valid_quarantined),
                        "status": "ACTIVE",
                        "reason": "tampered original",
                    },
                    {
                        "original_path": str(scan_root / "restored-safe.pdf"),
                        "quarantine_path": str(outside_quarantined),
                        "status": "ACTIVE",
                        "reason": "tampered quarantine",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = restore_quarantined_items(
        str(scan_root),
        [str(valid_quarantined), str(outside_quarantined)],
    )

    summary = result["summary"]
    rows = result["results"]
    assert isinstance(summary, dict)
    assert isinstance(rows, list)
    assert summary["failed"] == 2
    assert all(row["status"] == "FAILED" for row in rows)
    assert "manifest original_path escapes scan root" in str(rows[0]["error_message"])
    assert "manifest quarantine_path escapes quarantine root" in str(rows[1]["error_message"])
    assert valid_quarantined.exists()
    assert outside_quarantined.exists()


def test_scan_local_folder_limits_similar_name_comparisons(monkeypatch, tmp_path: Path):
    for index in range(120):
        (tmp_path / f"report-copy-{index}.txt").write_text("payload", encoding="utf-8")

    comparisons: list[tuple[str, str]] = []
    original = folder_organizer._looks_similar_name

    def tracking_similarity(left: str, right: str) -> bool:
        comparisons.append((left, right))
        return original(left, right)

    monkeypatch.setattr(folder_organizer, "_looks_similar_name", tracking_similarity)

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=500, stale_days=0, large_file_bytes=1024 * 1024)

    assert len(comparisons) <= SIMILAR_NAME_COMPARISON_LIMIT
    notes = [str(item) for item in scan.get("notes", [])]
    assert any("Similar-name detection skipped" in note for note in notes)


def test_scan_local_folder_surfaces_similar_name_notes(tmp_path: Path):
    (tmp_path / "invoice-2024.txt").write_text("a", encoding="utf-8")
    (tmp_path / "invoice-2025.txt").write_text("b", encoding="utf-8")

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=50, stale_days=0, large_file_bytes=1024 * 1024)

    records = cast(list[dict[str, object]], scan["records"])
    similar_candidates = [record for record in records if any("similar name candidate" in str(reason) for reason in record["candidate_reasons"])]
    assert len(similar_candidates) == 2


def test_duplicate_classification_distinguishes_same_content_same_name_and_similar_name(tmp_path: Path):
    same_content_a = tmp_path / "a" / "shared.txt"
    same_content_b = tmp_path / "b" / "renamed.txt"
    same_name_first = tmp_path / "c" / "report.txt"
    same_name_other = tmp_path / "d" / "report.txt"
    similar_name = tmp_path / "e" / "report-final.txt"
    for path in (same_content_a, same_content_b, same_name_first, same_name_other, similar_name):
        path.parent.mkdir(parents=True, exist_ok=True)
    same_content_a.write_text("same payload", encoding="utf-8")
    same_content_b.write_text("same payload", encoding="utf-8")
    same_name_first.write_text("different payload one", encoding="utf-8")
    same_name_other.write_text("different payload", encoding="utf-8")
    similar_name.write_text("another payload", encoding="utf-8")

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=0, large_file_bytes=10**9)
    records = {row["path"]: row for row in scan["records"]}

    assert records[str(same_content_a)]["duplicate_type"] == "same_content_duplicate"
    assert records[str(same_content_b)]["duplicate_type"] == "same_content_duplicate"
    assert records[str(same_name_first)]["duplicate_type"] == "same_name_candidate"
    assert records[str(same_name_other)]["duplicate_type"] == "same_name_candidate"
    assert records[str(similar_name)]["duplicate_type"] == "similar_name_candidate"


def test_duplicate_preview_and_manifest_keep_duplicate_reason(tmp_path: Path):
    first = tmp_path / "one" / "duplicate.txt"
    second = tmp_path / "two" / "duplicate.txt"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=0, large_file_bytes=10**9)
    preview = run_folder_organizer(scan, [str(first)], dry_run=True)
    moved = run_folder_organizer(scan, [str(first)], dry_run=False)

    preview_row = preview["results"][0]
    moved_row = moved["results"][0]
    quarantine_item = list_quarantine_items(str(tmp_path))[0]

    assert preview_row["duplicate_type"] == "same_name_candidate"
    assert "same filename appears more than once" in str(preview_row["duplicate_reason"])
    assert moved_row["duplicate_type"] == "same_name_candidate"
    assert quarantine_item["duplicate_type"] == "same_name_candidate"
    assert "same filename appears more than once" in str(quarantine_item["duplicate_reason"])


def test_same_content_duplicate_detects_empty_files(tmp_path: Path):
    first = tmp_path / "left" / "empty-a.txt"
    second = tmp_path / "right" / "empty-b.txt"
    first.parent.mkdir(parents=True, exist_ok=True)
    second.parent.mkdir(parents=True, exist_ok=True)
    first.write_bytes(b"")
    second.write_bytes(b"")

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=0, large_file_bytes=10**9)
    duplicate_types = {row["duplicate_type"] for row in scan["records"]}

    assert "same_content_duplicate" in duplicate_types


def test_duplicate_hash_failure_does_not_crash(monkeypatch, tmp_path: Path):
    target = tmp_path / "locked.txt"
    peer = tmp_path / "peer.txt"
    target.write_text("locked", encoding="utf-8")
    peer.write_text("peer!!", encoding="utf-8")

    import folder_organizer as organizer_module

    monkeypatch.setattr(organizer_module, "_hash_file", lambda _path: (None, "hash unavailable: blocked"))

    scan = scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=0, large_file_bytes=10**9)

    assert all(row["duplicate_reason"] == "hash unavailable: blocked" for row in scan["records"])


def test_duplicate_hashing_skips_unique_file_sizes(monkeypatch, tmp_path: Path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("one", encoding="utf-8")
    second.write_text("two-two", encoding="utf-8")

    import folder_organizer as organizer_module

    hashed_paths: list[str] = []
    original_hash = organizer_module._hash_file

    def tracking_hash(path: Path):
        hashed_paths.append(str(path))
        return original_hash(path)

    monkeypatch.setattr(organizer_module, "_hash_file", tracking_hash)

    scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=0, large_file_bytes=10**9)

    assert hashed_paths == []


def test_duplicate_hashing_only_hashes_same_size_groups(monkeypatch, tmp_path: Path):
    first = tmp_path / "a" / "first.txt"
    second = tmp_path / "b" / "second.txt"
    third = tmp_path / "c" / "third.txt"
    for path in (first, second, third):
        path.parent.mkdir(parents=True, exist_ok=True)
    first.write_text("same-size-a", encoding="utf-8")
    second.write_text("same-size-b", encoding="utf-8")
    third.write_text("different", encoding="utf-8")

    import folder_organizer as organizer_module

    hashed_paths: list[str] = []
    original_hash = organizer_module._hash_file

    def tracking_hash(path: Path):
        hashed_paths.append(str(path))
        return original_hash(path)

    monkeypatch.setattr(organizer_module, "_hash_file", tracking_hash)

    scan_local_folder(str(tmp_path), recursive=True, max_files=100, stale_days=0, large_file_bytes=10**9)

    assert sorted(hashed_paths) == sorted([str(first), str(second)])
