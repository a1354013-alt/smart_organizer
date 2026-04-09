from __future__ import annotations

from pathlib import Path

from core import FileProcessor
from services import reclassify_record
from storage import StorageManager


def test_manual_override_persists_and_reclassify_resets(tmp_path: Path):
    db = tmp_path / "t.db"
    repo = tmp_path / "repo"
    uploads = tmp_path / "uploads"
    storage = StorageManager(str(db), str(repo), str(uploads))

    # Create a file record
    processor = FileProcessor()
    png_bytes = b"\x89PNG\r\n\x1a\n" + (b"0" * 16)
    created = storage.create_temp_file("Screenshot_1.png", png_bytes, "deadbeef" * 8, "photo")
    assert created["success"] is True
    file_id = int(created["file_id"])

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-01-01",
            "main_topic": "旅行",
            "summary": "",
            "content": "",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "rule reason",
            "final_decision_reason": "手動覆寫：選擇「旅行」",
            "manual_override": True,
            "tag_scores": {"旅行": 1.0},
        },
    )

    info = storage.get_file_by_id(file_id)
    assert info is not None
    assert int(info.get("manual_override") or 0) == 1
    assert "手動覆寫" in (info.get("final_decision_reason") or "")
    assert (info.get("decision_source") or "") in {"MANUAL_OVERRIDE", ""}
    assert (info.get("last_manual_topic") or "") in {"旅行", ""}

    # Reclassify should reset manual_override and set a clear final_decision_reason
    new_topic = reclassify_record(
        storage=storage,
        processor=processor,
        file_id=file_id,
        processing_options={"enable_ocr": False, "enable_pdf_preview": False},
    )
    assert new_topic
    info2 = storage.get_file_by_id(file_id)
    assert info2 is not None
    assert int(info2.get("manual_override") or 0) == 0
    assert "重新分類（規則引擎）" in (info2.get("final_decision_reason") or "")
    assert (info2.get("decision_source") or "") in {"RULE_RECLASSIFY", ""}
    # manual traces should remain (not wiped by reclassify)
    assert (info2.get("last_manual_topic") or "") in {"旅行", ""}
