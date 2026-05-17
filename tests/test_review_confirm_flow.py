from __future__ import annotations

import pytest

from contracts import ExtractedMetadata
from services import AnalysisResult, build_confirmed_results


def _metadata() -> ExtractedMetadata:
    return {
        "file_type": "document",
        "standard_date": "2026-01-01",
        "extracted_text": "invoice text",
        "is_scanned": False,
        "preview_path": None,
        "ocr_error": None,
        "notes": [],
    }


def _result(file_id: int = 1) -> AnalysisResult:
    return AnalysisResult(
        file_id=file_id,
        original_name="invoice.pdf",
        file_type="document",
        standard_date="2026-01-01",
        main_topic="Invoices",
        suggested_main_topic="Invoices",
        tag_scores={"Invoices": 1.0},
        classification_reason="rule matched",
        final_decision_reason="rule decision",
        metadata=_metadata(),
        preview_path=None,
        is_scanned=False,
        summary=None,
        manual_override=False,
    )


class StubProcessor:
    def sync_manual_topic(self, chosen_topic, tag_scores, file_type):
        assert file_type == "document"
        return {chosen_topic: 1.0, **dict(tag_scores or {})}


def test_build_confirmed_results_accepts_review_flow_kwargs():
    confirmed = build_confirmed_results(
        [_result()],
        processor=StubProcessor(),
        selected_topics={1: "Tax"},
        summaries={1: "manual summary"},
    )

    assert len(confirmed) == 1
    item = confirmed[0]
    assert item.main_topic == "Tax"
    assert item.summary == "manual summary"
    assert item.manual_override is True
    assert item.tag_scores["Tax"] == 1.0


def test_build_confirmed_results_keeps_execute_flow_shape():
    confirmed = build_confirmed_results(
        [_result()],
        processor=StubProcessor(),
        selected_topics={1: "Invoices"},
        summaries={1: "kept summary"},
    )

    item = confirmed[0]
    assert item.file_id == 1
    assert item.original_name == "invoice.pdf"
    assert item.standard_date == "2026-01-01"
    assert item.metadata["extracted_text"] == "invoice text"
    assert item.summary == "kept summary"
    assert hasattr(item, "main_topic")
    assert hasattr(item, "manual_override")


def test_build_confirmed_results_without_overrides_clones_result():
    original = _result()
    confirmed = build_confirmed_results([original])
    item = confirmed[0]

    assert item is not original
    assert item.main_topic == original.main_topic
    assert item.summary == original.summary
    assert item.tag_scores == original.tag_scores


def test_build_confirmed_results_handles_multiple_items_and_summaries():
    first = _result(1)
    second = _result(2)
    confirmed = build_confirmed_results([first, second], summaries={2: "second summary"})

    assert [item.file_id for item in confirmed] == [1, 2]
    assert confirmed[0].summary == first.summary
    assert confirmed[1].summary == "second summary"


def test_review_manual_override_requires_processor_safety_gate():
    with pytest.raises(ValueError, match="processor is required"):
        build_confirmed_results([_result()], selected_topics={1: "Tax"})
