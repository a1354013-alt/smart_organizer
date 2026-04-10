from __future__ import annotations

from contracts import ExtractedMetadata
from core import DOCUMENT_TAGS, FileProcessor
from services import AnalysisResult, apply_manual_topic_override, generate_summary_suggestion


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
    original_topic = DOCUMENT_TAGS[0]
    chosen_topic = DOCUMENT_TAGS[1]
    result = AnalysisResult(
        file_id=1,
        original_name="invoice.pdf",
        file_type="document",
        standard_date="2026-01-01",
        main_topic=original_topic,
        suggested_main_topic=original_topic,
        tag_scores={original_topic: 1.0},
        classification_reason="rule",
        final_decision_reason="rule decision",
        metadata=_metadata(),
        preview_path=None,
        is_scanned=False,
    )

    updated = apply_manual_topic_override(
        result,
        processor=processor,
        chosen_topic=chosen_topic,
        summary="manual summary",
    )

    assert updated.main_topic == chosen_topic
    assert updated.manual_override is True
    assert updated.final_decision_reason
    assert updated.tag_scores.get(chosen_topic) == 1.0
    assert updated.summary == "manual summary"


def test_generate_summary_suggestion_uses_service_boundary():
    class StubProcessor:
        def get_llm_summary(self, text, file_type, enabled=True):
            assert text == "invoice"
            assert file_type == "document"
            assert enabled is True
            return "short summary", ["invoice"]

    result = AnalysisResult(
        file_id=2,
        original_name="invoice.pdf",
        file_type="document",
        standard_date="2026-01-01",
        main_topic="invoice",
        suggested_main_topic="invoice",
        tag_scores={"invoice": 1.0},
        classification_reason="rule",
        final_decision_reason="rule decision",
        metadata=_metadata(),
        preview_path=None,
        is_scanned=False,
    )

    suggestion = generate_summary_suggestion(result, processor=StubProcessor())

    assert suggestion.summary == "short summary"
    assert suggestion.llm_tags == ["invoice"]
