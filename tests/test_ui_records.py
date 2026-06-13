from __future__ import annotations

import hashlib

from i18n import t
from storage import StorageManager
from ui_records import build_records_maintenance_actions


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes(label: str) -> bytes:
    return f"%PDF-1.4\n% {label}\n%%EOF\n".encode()


def _create_record(
    storage: StorageManager,
    name: str,
    *,
    topic: str,
    summary: str,
    file_type: str = "document",
    status: str | None = None,
    created_at: str | None = None,
) -> int:
    payload = _minimal_pdf_bytes(name)
    result = storage.create_temp_file(name, payload, _sha256(payload), file_type)
    file_id = int(result["file_id"])
    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-05-17",
            "main_topic": topic,
            "summary": summary,
            "content": summary,
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "test rule",
            "final_decision_reason": "reviewed",
            "manual_override": False,
            "tag_scores": {topic: 1.0},
        },
    )
    if status or created_at:
        conn = storage._get_connection()
        try:
            conn.execute(
                "UPDATE files SET status = COALESCE(?, status), created_at = COALESCE(?, created_at) WHERE file_id = ?",
                (status, created_at, file_id),
            )
            conn.commit()
        finally:
            conn.close()
    return file_id


def test_records_maintenance_actions_visible_without_rows():
    actions = build_records_maintenance_actions([])
    labels = {str(action["label"]) for action in actions}

    assert t("search_records.maintenance_refresh") in labels
    assert t("search_records.maintenance_rebuild_fts") in labels
    assert t("search_records.maintenance_reclassify") in labels
    reclassify = next(action for action in actions if action["label"] == t("search_records.maintenance_reclassify"))
    assert reclassify["enabled"] is False


def test_records_page_filters_pagination_and_stable_sorting():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    first_id = _create_record(
        storage,
        "invoice-a.pdf",
        topic="Invoices",
        summary="alpha contract",
        status="PROCESSED",
        created_at="2026-05-16T09:00:00",
    )
    second_id = _create_record(
        storage,
        "invoice-b.pdf",
        topic="Invoices",
        summary="beta contract",
        status="COMPLETED",
        created_at="2026-05-17T09:00:00",
    )
    _create_record(
        storage,
        "photo.pdf",
        topic="Photos",
        summary="holiday",
        status="PROCESSED",
        created_at="2026-05-15T09:00:00",
    )

    filtered = storage.get_records_page(
        limit=10,
        offset=0,
        main_topic="Invoices",
        search="contract",
        date_from="2026-05-16",
        date_to="2026-05-17",
    )
    first_page = storage.get_records_page(limit=1, offset=0)
    second_page = storage.get_records_page(limit=1, offset=1)

    assert filtered["total"] == 2
    assert [item["file_id"] for item in filtered["items"]] == [second_id, first_id]
    assert first_page["items"][0]["file_id"] == second_id
    assert second_page["items"][0]["file_id"] == first_id


def test_search_records_empty_keyword_hits_and_no_results():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    file_id = _create_record(
        storage,
        "invoice.pdf",
        topic="Invoices",
        summary="quarterly tax invoice",
        status="PROCESSED",
    )

    assert storage.search_content("") == []
    hits = storage.search_content("tax")
    misses = storage.search_content("not-present")

    assert any(item["file_id"] == file_id for item in hits)
    assert misses == []


def test_record_filter_values_reflect_loaded_history_states():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    _create_record(storage, "restore-history.pdf", topic="Archive", summary="restore", status="RESTORED")
    _create_record(storage, "quarantine-history.pdf", topic="Archive", summary="quarantine", status="QUARANTINED")

    values = storage.get_record_filter_values()

    assert "RESTORED" in values["status"]
    assert "QUARANTINED" in values["status"]
    assert values["main_topic"] == ["Archive"]


def test_get_all_records_paginates_beyond_recent_limit():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    for index in range(505):
        _create_record(storage, f"record-{index}.pdf", topic="Archive", summary=f"summary {index}")

    all_records = storage.get_all_records()
    recent_records = storage.get_recent_records(limit=500)

    assert len(all_records) == 505
    assert len(recent_records) == 500
