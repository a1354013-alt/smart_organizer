from __future__ import annotations

import csv
from pathlib import Path

from folder_report import export_folder_report_csv, export_folder_report_markdown
from folder_service import (
    get_quarantine_items_safe,
    preview_selected_actions,
    quarantine_selected_files,
    restore_quarantine_selection,
    scan_folder,
)
from malware_scanner import ClamAvStatus, MalwareScanResult


def test_folder_service_end_to_end_quarantine_restore_and_report(tmp_path: Path):
    duplicate_a = tmp_path / "dupes" / "report.txt"
    duplicate_b = tmp_path / "archive" / "report.txt"
    old_log = tmp_path / "logs" / "old.log"
    keeper = tmp_path / "keep.txt"
    collision_target = tmp_path / "dupes" / "report.txt"

    for path in (duplicate_a, duplicate_b, old_log):
        path.parent.mkdir(parents=True, exist_ok=True)
    duplicate_a.write_text("same name, original", encoding="utf-8")
    duplicate_b.write_text("same name, different content", encoding="utf-8")
    old_log.write_text("old log", encoding="utf-8")
    keeper.write_text("keep me", encoding="utf-8")

    scan_result = scan_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )
    records = {row["path"]: row for row in scan_result["records"]}
    selected_paths = [str(duplicate_a), str(old_log)]

    assert records[str(duplicate_a)]["duplicate_type"] == "same_name_candidate"
    assert records[str(old_log)]["recommendation"] in {"Safe to review", "Needs manual check"}

    preview = preview_selected_actions(scan_result, selected_paths)
    assert preview["summary"]["preview"] == 2
    assert all(row["status"] == "PREVIEW" for row in preview["results"])

    operation_result, refreshed_scan, report_snapshot = quarantine_selected_files(
        scan_result,
        selected_paths,
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )
    assert operation_result["summary"]["success"] == 2
    assert not duplicate_a.exists()
    assert not old_log.exists()

    quarantine_items, warnings = get_quarantine_items_safe(str(tmp_path))
    assert warnings == []
    assert len(quarantine_items) == 2

    collision_target.write_text("new user file after quarantine", encoding="utf-8")
    restore_result, restored_scan = restore_quarantine_selection(
        str(tmp_path),
        [str(item["quarantine_path"]) for item in quarantine_items],
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )
    assert restore_result["summary"]["success"] == 2
    assert collision_target.read_text(encoding="utf-8") == "new user file after quarantine"

    restored_paths = {Path(str(row["new_path"])) for row in restore_result["results"]}
    assert tmp_path / "dupes" / "report__1.txt" in restored_paths
    assert tmp_path / "logs" / "old.log" in restored_paths
    assert refreshed_scan is not None
    assert restored_scan is not None
    assert report_snapshot is not None

    markdown_report = export_folder_report_markdown(report_snapshot, operation_result)
    csv_payload = export_folder_report_csv(report_snapshot, operation_result).decode("utf-8-sig")
    csv_rows = list(csv.DictReader(csv_payload.splitlines()))

    assert "Smart Organizer Report" in markdown_report
    assert "report.txt" in markdown_report
    assert "old.log" in markdown_report
    assert len(csv_rows) == 2
    assert {row["status"] for row in csv_rows} == {"SUCCESS"}
    assert "malware_status" in csv_rows[0]


def test_infected_candidates_are_not_quarantined(monkeypatch, tmp_path: Path):
    infected_file = tmp_path / "payload.exe"
    infected_file.write_text("payload", encoding="utf-8")

    monkeypatch.setattr(
        "folder_organizer.get_clamav_status",
        lambda _days: ClamAvStatus(
            availability="available",
            clamscan_path="C:/ClamAV/clamscan.exe",
            freshclam_path="C:/ClamAV/freshclam.exe",
            database_version="27315",
            database_date="2026-06-10",
            database_age_days=0,
            message="ready",
        ),
    )
    monkeypatch.setattr(
        "folder_organizer.scan_files",
        lambda paths, **kwargs: {
            str(path.resolve()): MalwareScanResult(
                status="infected",
                scanner="ClamAV",
                file_path=str(path.resolve()),
                threat_name="Eicar-Test-Signature",
                message="FOUND",
                return_code=1,
            )
            for path in paths
        },
    )

    scan_result = scan_folder(
        str(tmp_path),
        recursive=True,
        max_files=20,
        stale_days=0,
        large_file_bytes=1,
        enable_malware_scan=True,
    )
    record = scan_result["records"][0]

    assert record["malware_status"] == "infected"
    assert record["recommendation"] == "Do not touch"

    preview = preview_selected_actions(scan_result, [str(infected_file)])
    assert preview["summary"]["skipped"] == 1
    assert "marked infected" in str(preview["results"][0]["error_message"])

    operation_result, refreshed_scan, report_snapshot = quarantine_selected_files(
        scan_result,
        [str(infected_file)],
        recursive=True,
        max_files=20,
        stale_days=0,
        large_file_bytes=1,
        enable_malware_scan=True,
    )

    assert operation_result["summary"]["success"] == 0
    assert operation_result["summary"]["skipped"] == 1
    assert infected_file.exists()
    quarantine_items, warnings = get_quarantine_items_safe(str(tmp_path))
    assert warnings == []
    assert quarantine_items == []
    assert refreshed_scan is not None
    assert report_snapshot is not None

    markdown_report = export_folder_report_markdown(report_snapshot, operation_result)
    csv_payload = export_folder_report_csv(report_snapshot, operation_result).decode("utf-8-sig")

    assert "infected" in markdown_report.lower()
    assert "malware_status" in csv_payload
