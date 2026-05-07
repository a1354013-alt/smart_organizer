from __future__ import annotations

import csv
from pathlib import Path
from typing import cast

from folder_report import export_folder_report_csv, export_folder_report_markdown
from folder_service import quarantine_selected_files, resolve_report_inputs
from folder_organizer import scan_local_folder


def test_quarantine_report_uses_pre_operation_snapshot(tmp_path: Path):
    target = tmp_path / "snapshot-target.txt"
    target.write_text("stale data", encoding="utf-8")
    scan_before = scan_local_folder(
        str(tmp_path),
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )

    operation_result, refreshed_scan, snapshot = quarantine_selected_files(
        scan_before,
        [str(target)],
        recursive=True,
        max_files=100,
        stale_days=0,
        large_file_bytes=1,
    )

    refreshed_stats = cast(dict[str, object], refreshed_scan["stats"])
    assert refreshed_stats["scanned_files"] == 0

    export_scan, export_operation = resolve_report_inputs(refreshed_scan, snapshot, operation_result)
    markdown_report = export_folder_report_markdown(export_scan, export_operation)
    csv_payload = export_folder_report_csv(export_scan, export_operation)
    csv_rows = list(csv.DictReader(csv_payload.decode("utf-8-sig").splitlines()))

    assert "- Scanned files: 1" in markdown_report
    assert "- Candidate files: 1" in markdown_report
    assert "- Quarantined / moved: 1" in markdown_report
    assert str(tmp_path) in markdown_report
    assert csv_rows[0]["scan_path"] == str(tmp_path)
    assert csv_rows[0]["status"] == "SUCCESS"
    assert csv_rows[0]["original_path"] == str(target)
