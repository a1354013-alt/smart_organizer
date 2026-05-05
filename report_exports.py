from __future__ import annotations

import csv
import html
from io import StringIO


def escape_markdown_table_cell(value: object) -> str:
    text = str(value if value not in (None, "") else "-")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("|", r"\|").replace("\n", "<br>")


def escape_display_text(value: object) -> str:
    return html.escape(str(value if value not in (None, "") else "-"), quote=True)


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
                    escape_markdown_table_cell(record.get("file_id")),
                    escape_markdown_table_cell(record.get("original_name")),
                    escape_markdown_table_cell(record.get("file_type")),
                    escape_markdown_table_cell(record.get("main_topic")),
                    escape_markdown_table_cell(record.get("status")),
                    escape_markdown_table_cell(record.get("created_at")),
                    escape_markdown_table_cell(record.get("last_error")),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"
