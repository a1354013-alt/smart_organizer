from __future__ import annotations

import csv
from io import StringIO

from report_exports import export_records_csv, export_records_markdown
from storage import StorageManager


def test_create_temp_file_stores_created_at_as_utc_iso():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    payload = b"%PDF-1.4\n% demo\n%%EOF\n"

    created = storage.create_temp_file("invoice.pdf", payload, "hash-time-policy", "document")
    record = storage.get_file_by_id(int(created["file_id"]))

    assert created["success"] is True
    assert record is not None
    assert str(record["created_at"]).endswith("+00:00")
    assert "T" in str(record["created_at"])


def test_record_exports_mark_timezone_and_normalize_naive_values():
    records = [
        {
            "file_id": 1,
            "original_name": "invoice.pdf",
            "file_type": "document",
            "standard_date": "2026-05-17",
            "main_topic": "Invoices",
            "all_tags": "Invoices",
            "status": "PROCESSED",
            "manual_override": False,
            "last_error": "",
            "created_at": "2026-05-17T10:00:00",
            "final_path": "repo/invoice.pdf",
        }
    ]

    csv_payload = export_records_csv(records)
    markdown_payload = export_records_markdown(records)
    row = list(csv.DictReader(StringIO(csv_payload)))[0]

    assert row["created_at"] == "2026-05-17T10:00:00+00:00"
    assert "UTC ISO 8601" in markdown_payload
    assert "2026-05-17T10:00:00+00:00" in markdown_payload
