from __future__ import annotations

import csv
import json
from datetime import datetime
from io import StringIO
from pathlib import Path

from report_exports import (
    escape_display_text,
    export_records_csv,
    export_records_markdown,
    export_rows_to_csv,
    export_rows_to_json,
    export_rows_to_markdown,
)


def test_record_exports_escape_markdown_and_csv_fields():
    records = [
        {
            "file_id": 1,
            "original_name": 'bad|name,\n"quoted".txt',
            "file_type": "document",
            "main_topic": "Topic",
            "status": "READY",
            "created_at": "2026-05-05T12:00:00+00:00",
            "last_error": "<script>alert(1)</script>",
            "standard_date": "2026-05-05",
            "all_tags": "x",
            "manual_override": False,
            "final_path": None,
        }
    ]

    markdown_payload = export_records_markdown(records)
    csv_payload = export_records_csv(records)
    rows = list(csv.DictReader(StringIO(csv_payload)))

    assert r"bad\|name," in markdown_payload
    assert "<br>" in markdown_payload
    assert "<script>alert(1)</script>" in markdown_payload
    assert rows[0]["original_name"] == 'bad|name,\n"quoted".txt'
    assert rows[0]["last_error"] == "<script>alert(1)</script>"
    assert escape_display_text("<script>") == "&lt;script&gt;"


def test_generic_markdown_export_includes_classification_risk_and_recommendation():
    rows = [
        {
            "filename": 'invoice|May,\n"final".pdf',
            "classification": "Receipt",
            "risk_level": "needs_manual_check",
            "recommended_action": "dry-run first",
        }
    ]

    payload = export_rows_to_markdown(rows, title="Smart Organizer Report")

    assert payload.startswith("# Smart Organizer Report")
    assert r"invoice\|May," in payload
    assert "<br>" in payload
    assert "Receipt" in payload
    assert "needs_manual_check" in payload
    assert "dry-run first" in payload


def test_records_csv_has_stable_field_order_and_escapes_chinese_content():
    records = [
        {
            "file_id": 7,
            "original_name": '合約,第一版\n"簽核".pdf',
            "file_type": "document",
            "standard_date": "2026-05-17",
            "main_topic": "合約",
            "all_tags": "重要,中文",
            "status": "PROCESSED",
            "manual_override": True,
            "last_error": "",
            "created_at": "2026-05-17T10:00:00",
            "final_path": "repo/合約.pdf",
        }
    ]

    payload = export_records_csv(records)
    header = payload.splitlines()[0].split(",")
    parsed = list(csv.DictReader(StringIO(payload)))

    assert header == [
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
    assert parsed[0]["original_name"] == '合約,第一版\n"簽核".pdf'
    assert parsed[0]["main_topic"] == "合約"


def test_generic_json_export_round_trips_paths_and_datetimes():
    payload = export_rows_to_json(
        [
            {
                "path": Path("repo") / "invoice.pdf",
                "created_at": datetime(2026, 5, 17, 10, 0, 0),
                "score": 0.88,
            }
        ]
    )

    decoded = json.loads(payload)

    assert decoded == [
        {
            "path": str(Path("repo") / "invoice.pdf"),
            "created_at": "2026-05-17T10:00:00",
            "score": 0.88,
        }
    ]


def test_empty_and_large_generic_exports_remain_stable():
    assert export_rows_to_csv([]) == ""
    assert "_No records available._" in export_rows_to_markdown([])
    rows = [{"file_id": index, "name": f"file-{index}.txt"} for index in range(100)]

    csv_rows = list(csv.DictReader(StringIO(export_rows_to_csv(rows))))
    json_rows = json.loads(export_rows_to_json(rows))
    markdown_payload = export_rows_to_markdown(rows)

    assert len(csv_rows) == 100
    assert len(json_rows) == 100
    assert "| 99 | file-99.txt |" in markdown_payload
