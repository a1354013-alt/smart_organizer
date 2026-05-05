from __future__ import annotations

import csv
from io import StringIO

from folder_models import dict_object, human_bytes, object_list, safe_int

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


def export_folder_report_markdown(
    scan_result: dict[str, object],
    operation_result: dict[str, object] | None = None,
) -> str:
    stats = dict_object(scan_result.get("stats"))
    rows = [dict_object(item) for item in object_list((operation_result or {}).get("results"))]
    lines = [
        "# Smart Organizer Report",
        "",
        f"- Scan path: `{scan_result.get('path')}`",
        f"- Scanned at: {scan_result.get('scanned_at')}",
        f"- Scanned files: {stats.get('scanned_files', 0)}",
        f"- Total size: {human_bytes(safe_int(stats.get('total_bytes')))}",
        f"- Stale candidates: {stats.get('stale_candidates', 0)}",
        f"- Large file candidates: {stats.get('large_candidates', 0)}",
        f"- Processed files: {len(rows)}",
        f"- Success: {sum(1 for row in rows if row.get('status') == 'SUCCESS')}",
        f"- Failed: {sum(1 for row in rows if row.get('status') == 'FAILED')}",
        f"- Skipped: {sum(1 for row in rows if row.get('status') == 'SKIPPED')}",
        "",
        "| Original path | New path | Size | Last modified | Status | Failure reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("original_path") or "-"),
                    str(row.get("new_path") or "-"),
                    human_bytes(safe_int(row.get("file_size"))),
                    str(row.get("last_modified") or "-"),
                    str(row.get("status") or "-"),
                    str(row.get("error_message") or "-"),
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
