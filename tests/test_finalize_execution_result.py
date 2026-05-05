from __future__ import annotations

import hashlib

from services import AnalysisResult, finalize_one_file
from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _metadata():
    return {
        "file_type": "document",
        "standard_date": "2026-01-01",
        "extracted_text": "",
        "is_scanned": False,
        "preview_path": None,
        "ocr_error": None,
        "notes": [],
    }


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_finalize_one_file_returns_error_message_on_failure():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)
    res = storage.create_temp_file("broken.pdf", payload, file_hash, "document")
    assert res["success"] is True
    file_id = int(res["file_id"])

    conn = storage._get_connection()
    try:
        conn.execute("UPDATE files SET temp_path = ? WHERE file_id = ?", ("mem://uploads/missing.pdf", file_id))
        conn.commit()
    finally:
        conn.close()

    result = AnalysisResult(
        file_id=file_id,
        original_name="broken.pdf",
        file_type="document",
        standard_date="2026-01-01",
        main_topic="Documents",
        suggested_main_topic="Documents",
        tag_scores={"Documents": 1.0},
        classification_reason="rule",
        final_decision_reason="rule",
        metadata=_metadata(),
        preview_path=None,
        is_scanned=False,
    )
    execution = finalize_one_file(result, storage=storage)
    assert execution.status == "FAILED"
    assert execution.error_message
