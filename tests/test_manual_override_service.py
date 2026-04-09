from __future__ import annotations

from contracts import ExtractedMetadata
from core import FileProcessor
from services import AnalysisResult, apply_manual_topic_override


def _metadata() -> ExtractedMetadata:
    return {
        "file_type": "document",
        "standard_date": "2026-01-01",
        "extracted_text": "invoice",
        "is_scanned": False,
        "preview_path": None,
        "ocr_error": None,
        "notes": [],
    }


def test_apply_manual_topic_override_updates_decision_fields_consistently():
    processor = FileProcessor()
    result = AnalysisResult(
        file_id=1,
        original_name="invoice.pdf",
        file_type="document",
        standard_date="2026-01-01",
        main_topic="發票",
        suggested_main_topic="發票",
        tag_scores={"發票": 1.0},
        classification_reason="rule",
        final_decision_reason="採用規則建議",
        metadata=_metadata(),
        preview_path=None,
        is_scanned=False,
    )

    updated = apply_manual_topic_override(
        result,
        processor=processor,
        chosen_topic="合約",
        summary="manual summary",
    )

    assert updated.main_topic == "合約"
    assert updated.manual_override is True
    assert "手動覆寫" in updated.final_decision_reason
    assert updated.tag_scores.get("合約") == 1.0
    assert updated.summary == "manual summary"

