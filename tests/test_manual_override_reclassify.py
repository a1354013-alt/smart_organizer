from __future__ import annotations

from pathlib import Path

from core import FileProcessor
from services import reclassify_record
from storage import StorageManager


def _as_text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _as_int(value: object) -> int:
    if isinstance(value, int):
        return value
    return int(str(value or 0))


def test_manual_override_persists_and_reclassify_resets(tmp_path: Path):
    db = tmp_path / "t.db"
    repo = tmp_path / "repo"
    uploads = tmp_path / "uploads"
    storage = StorageManager(str(db), str(repo), str(uploads))

    processor = FileProcessor()
    png_bytes = b"\x89PNG\r\n\x1a\n" + (b"0" * 16)
    created = storage.create_temp_file("Screenshot_1.png", png_bytes, "deadbeef" * 8, "photo")
    assert created["success"] is True
    file_id = int(created["file_id"])

    storage.update_file_metadata(
        file_id,
        {
            "standard_date": "2026-01-01",
            "main_topic": "ManualTopic",
            "summary": "",
            "content": "",
            "is_scanned": False,
            "preview_path": None,
            "classification_reason": "rule reason",
            "final_decision_reason": "manual override",
            "manual_override": True,
            "tag_scores": {"ManualTopic": 1.0},
        },
    )

    info = storage.get_file_by_id(file_id)
    assert info is not None
    assert _as_int(info.get("manual_override")) == 1
    assert _as_text(info.get("final_decision_reason"))
    assert _as_text(info.get("decision_source")) in {"MANUAL_OVERRIDE", ""}
    assert _as_text(info.get("last_manual_topic")) in {"ManualTopic", ""}

    new_topic = reclassify_record(
        storage=storage,
        processor=processor,
        file_id=file_id,
        processing_options={"enable_ocr": False, "enable_pdf_preview": False},
    )
    assert new_topic

    info2 = storage.get_file_by_id(file_id)
    assert info2 is not None
    assert _as_int(info2.get("manual_override")) == 0
    assert _as_text(info2.get("final_decision_reason"))
    assert _as_text(info2.get("decision_source")) in {"RULE_RECLASSIFY", ""}
    assert _as_text(info2.get("last_manual_topic")) in {"ManualTopic", ""}
