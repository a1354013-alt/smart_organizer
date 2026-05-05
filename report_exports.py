from __future__ import annotations

import csv
from io import StringIO


def export_records_csv(records: list[dict[str, object]]) -> str:
    buffer = StringIO()
    fieldnames = [
        "file_id",
        "original_name",
        "file_type",
        "standard_date",
        "main_topic",
        "all_tags",
        "status",
        "manual_override",
        "last_error",
        "created_at",
        "final_path",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for record in records:
        writer.writerow({key: record.get(key) for key in fieldnames})
    return buffer.getvalue()


def export_records_markdown(records: list[dict[str, object]]) -> str:
    lines = [
        "# Filtered Records Export",
        "",
        "| ID | File | Type | Topic | Status | Created at | Last error |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(record.get("file_id") or "-"),
                    str(record.get("original_name") or "-"),
                    str(record.get("file_type") or "-"),
                    str(record.get("main_topic") or "-"),
                    str(record.get("status") or "-"),
                    str(record.get("created_at") or "-"),
                    str(record.get("last_error") or "-"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"
