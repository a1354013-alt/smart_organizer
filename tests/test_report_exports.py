from __future__ import annotations

import csv
from io import StringIO

from report_exports import escape_display_text, export_records_csv, export_records_markdown


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
