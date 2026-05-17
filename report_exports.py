from __future__ import annotations

import csv
import html
import json
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path


def escape_markdown_table_cell(value: object) -> str:
    text = str(value if value not in (None, "") else "-")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("|", r"\|").replace("\n", "<br>")


def escape_display_text(value: object) -> str:
    return html.escape(str(value if value not in (None, "") else "-"), quote=True)


def format_timestamp_for_export(value: object) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat(timespec="seconds")

    text = str(value).strip()
    if not text:
        return "-"
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def export_rows_to_csv(rows: Iterable[Mapping[str, object]]) -> str:
    materialized = [dict(row) for row in rows]
    if not materialized:
        return ""

    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(str(key))

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in materialized:
        writer.writerow({key: row.get(key, "") for key in fieldnames})
    return buffer.getvalue()


def export_rows_to_json(rows: Iterable[Mapping[str, object]]) -> str:
    return json.dumps(
        [{str(key): _json_safe(value) for key, value in row.items()} for row in rows],
        ensure_ascii=False,
        indent=2,
    )


def _json_safe(value: object) -> object:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    return value


def export_rows_to_markdown(
    rows: Iterable[Mapping[str, object]],
    *,
    title: str = "Records Export",
) -> str:
    materialized = [dict(row) for row in rows]
    lines = [f"# {escape_markdown_table_cell(title)}", ""]
    if not materialized:
        lines.append("_No records available._")
        return "\n".join(lines) + "\n"

    fieldnames: list[str] = []
    for row in materialized:
        for key in row:
            key_text = str(key)
            if key_text not in fieldnames:
                fieldnames.append(key_text)

    lines.append("| " + " | ".join(escape_markdown_table_cell(key) for key in fieldnames) + " |")
    lines.append("| " + " | ".join("---" for _ in fieldnames) + " |")
    for row in materialized:
        lines.append(
            "| "
            + " | ".join(escape_markdown_table_cell(row.get(key)) for key in fieldnames)
            + " |"
        )
    return "\n".join(lines) + "\n"


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
        row = {key: record.get(key) for key in fieldnames}
        row["created_at"] = format_timestamp_for_export(record.get("created_at"))
        writer.writerow(row)
    return buffer.getvalue()


def export_records_markdown(records: list[dict[str, object]]) -> str:
    lines = [
        "# Filtered Records Export",
        "",
        "Timestamps are stored and exported as UTC ISO 8601.",
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
                    escape_markdown_table_cell(format_timestamp_for_export(record.get("created_at"))),
                    escape_markdown_table_cell(record.get("last_error")),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"
