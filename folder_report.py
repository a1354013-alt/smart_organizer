from __future__ import annotations

import csv
from io import StringIO
from typing import Iterable

from folder_models import FolderActionResult, dict_object, human_bytes, object_list, safe_int
from report_exports import escape_markdown_table_cell

FOLDER_REPORT_FIELDNAMES = [
    "scan_path",
    "scanned_at",
    "original_path",
    "new_path",
    "file_size",
    "last_modified",
    "reason",
    "status",
    "error_message",
    "operation_id",
]


def summarize_folder_actions(actions: Iterable[FolderActionResult]) -> dict[str, int]:
    total = 0
    success = 0
    failed = 0

    for action in actions:
        total += 1
        if action.success:
            success += 1
        else:
            failed += 1

    return {
        "total": total,
        "success": success,
        "failed": failed,
    }


def export_folder_report_markdown(
    scan_result: dict[str, object],
    operation_result: dict[str, object] | None = None,
) -> str:
    stats = dict_object(scan_result.get("stats"))
    scan_records = [dict_object(item) for item in object_list(scan_result.get("records"))]
    rows = [dict_object(item) for item in object_list((operation_result or {}).get("results"))]
    operation_summary = dict_object((operation_result or {}).get("summary"))
    candidate_count = sum(1 for record in scan_records if record.get("candidate_reasons"))
    quarantine_destination = next(
        (
            str(row.get("new_path") or "")
            for row in rows
            if str(row.get("new_path") or "").strip()
        ),
        "-",
    )
    lines = [
        "# Smart Organizer Report",
        "",
        f"- Scan path: `{scan_result.get('path') or '-'}`",
        f"- Scanned at: {scan_result.get('scanned_at')}",
        f"- Scanned files: {stats.get('scanned_files', 0)}",
        f"- Total size: {human_bytes(safe_int(stats.get('total_bytes')))}",
        f"- Candidate files: {candidate_count}",
        f"- Stale candidates: {stats.get('stale_candidates', 0)}",
        f"- Large file candidates: {stats.get('large_candidates', 0)}",
        f"- Selected files: {operation_summary.get('selected', len(rows))}",
        f"- Quarantined / moved: {operation_summary.get('success', sum(1 for row in rows if row.get('status') == 'SUCCESS'))}",
        f"- Failed: {operation_summary.get('failed', sum(1 for row in rows if row.get('status') == 'FAILED'))}",
        f"- Skipped: {operation_summary.get('skipped', sum(1 for row in rows if row.get('status') == 'SKIPPED'))}",
        f"- Quarantine destination: `{quarantine_destination}`",
        f"- Generated at: {rows[-1].get('processed_at') if rows else scan_result.get('scanned_at')}",
        "",
        "| Original path | New path | Size | Last modified | Status | Failure reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    escape_markdown_table_cell(row.get("original_path")),
                    escape_markdown_table_cell(row.get("new_path")),
                    human_bytes(safe_int(row.get("file_size"))),
                    escape_markdown_table_cell(row.get("last_modified")),
                    escape_markdown_table_cell(row.get("status")),
                    escape_markdown_table_cell(row.get("error_message")),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def export_folder_report_csv(
    scan_result: dict[str, object],
    operation_result: dict[str, object] | None = None,
) -> bytes:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=FOLDER_REPORT_FIELDNAMES)
    writer.writeheader()

    for row_obj in object_list((operation_result or {}).get("results")):
        row = dict_object(row_obj)
        writer.writerow(
            {
                "scan_path": scan_result.get("path"),
                "scanned_at": scan_result.get("scanned_at"),
                "original_path": row.get("original_path"),
                "new_path": row.get("new_path"),
                "file_size": safe_int(row.get("file_size")),
                "last_modified": row.get("last_modified"),
                "reason": row.get("reason"),
                "status": row.get("status"),
                "error_message": row.get("error_message"),
                "operation_id": row.get("operation_id") or (operation_result or {}).get("operation_id"),
            }
        )

    return buffer.getvalue().encode("utf-8-sig")
