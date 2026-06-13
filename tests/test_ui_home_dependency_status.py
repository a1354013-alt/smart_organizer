from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import core_processor
from core import FileProcessor
from folder_models import Recommendation
from i18n import t
from ui_home import (
    DEPENDENCY_STATUS_SESSION_KEY,
    _candidate_row,
    _duplicate_type_label,
    cache_dependency_status,
    get_cached_dependency_status,
    limit_candidate_rows,
    merge_visible_selection,
    refresh_dependency_status,
    render_home,
    summarize_recommendations,
)
from ui_labels import recommendation_display_label, topic_display_label


class _Column:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_dependency_status_cache_starts_empty():
    session_state: dict[str, object] = {}

    assert get_cached_dependency_status(session_state) is None
    assert DEPENDENCY_STATUS_SESSION_KEY not in session_state


def test_refresh_dependency_status_calls_processor_once_and_caches(monkeypatch):
    captured: list[str] = []
    session_state: dict[str, object] = {}
    context = SimpleNamespace(
        processor=SimpleNamespace(get_dependency_status=lambda: {"system": {"ffmpeg": captured.append("called") is None}})
    )

    monkeypatch.setattr("ui_home.st.session_state", session_state)

    status = refresh_dependency_status(context)

    assert captured == ["called"]
    assert status == {"system": {"ffmpeg": True}}
    assert session_state[DEPENDENCY_STATUS_SESSION_KEY] == {"system": {"ffmpeg": True}}
    assert get_cached_dependency_status(session_state) == {"system": {"ffmpeg": True}}


def test_cache_dependency_status_normalizes_to_plain_dict():
    session_state: dict[str, object] = {}
    source = {"python": {"pypdf": True}}

    cached = cache_dependency_status(session_state, source)
    source["python"] = {"pypdf": False}

    assert cached == {"python": {"pypdf": True}}
    assert get_cached_dependency_status(session_state) == {"python": {"pypdf": True}}


def test_file_processor_dependency_status_checks_ffmpeg_lazily(monkeypatch):
    calls: list[bool] = []
    processor = FileProcessor()

    monkeypatch.setattr(core_processor, "FFMPEG_AVAILABLE", None)
    monkeypatch.setattr(core_processor, "_detect_ffmpeg_available", lambda: calls.append(True) or True)

    assert calls == []

    status = processor.get_dependency_status()

    assert calls == [True]
    assert status["system"]["ffmpeg"] is True


def test_ffmpeg_refresh_updates_ui_and_processing_from_unavailable_to_available(monkeypatch):
    session_state: dict[str, object] = {}
    states = iter([False, True])
    processor = FileProcessor()

    monkeypatch.setattr("ui_home.st.session_state", session_state)
    monkeypatch.setattr(core_processor, "FFMPEG_AVAILABLE", None)
    monkeypatch.setattr(core_processor, "_detect_ffmpeg_available", lambda: next(states))

    assert core_processor.get_ffmpeg_available() is False
    status = refresh_dependency_status(SimpleNamespace(processor=processor))

    assert status["system"]["ffmpeg"] is True
    assert core_processor.is_ffmpeg_available() is True


def test_ffmpeg_refresh_updates_ui_and_processing_from_available_to_unavailable(monkeypatch):
    session_state: dict[str, object] = {}
    states = iter([True, False])
    processor = FileProcessor()

    monkeypatch.setattr("ui_home.st.session_state", session_state)
    monkeypatch.setattr(core_processor, "FFMPEG_AVAILABLE", None)
    monkeypatch.setattr(core_processor, "_detect_ffmpeg_available", lambda: next(states))

    assert core_processor.get_ffmpeg_available() is True
    status = refresh_dependency_status(SimpleNamespace(processor=processor))

    assert status["system"]["ffmpeg"] is False
    assert core_processor.is_ffmpeg_available() is False


def test_summarize_recommendations_uses_shared_contract_labels():
    records = [
        {"recommendation": Recommendation.SAFE_TO_REVIEW.value},
        {"recommendation": Recommendation.NEEDS_MANUAL_CHECK.value},
        {"recommendation": Recommendation.DO_NOT_TOUCH.value},
    ]
    candidates = records[:2]

    summary = summarize_recommendations(records, candidates)

    assert summary == {
        Recommendation.SAFE_TO_REVIEW.value: 1,
        Recommendation.NEEDS_MANUAL_CHECK.value: 1,
        Recommendation.DO_NOT_TOUCH.value: 1,
    }


def test_recommendation_display_label_keeps_data_contract_and_localizes_ui_text():
    assert recommendation_display_label(Recommendation.SAFE_TO_REVIEW.value) == t("labels.recommendation.safe_to_review")
    assert recommendation_display_label(Recommendation.NEEDS_MANUAL_CHECK.value) == t(
        "labels.recommendation.needs_manual_check"
    )
    assert recommendation_display_label(Recommendation.DO_NOT_TOUCH.value) == t("labels.recommendation.do_not_touch")
    assert recommendation_display_label("Custom label") == "Custom label"


def test_topic_display_label_supports_locale_mapping_and_legacy_values():
    assert topic_display_label("document.invoice", locale="zh-TW") == "發票"
    assert topic_display_label("document.invoice", locale="en") == "Invoice"
    assert topic_display_label("發票", locale="en") == "Invoice"
    assert topic_display_label("Meeting", locale="zh-TW") == "會議錄影"


def test_duplicate_type_label_uses_localized_labels_and_fallback():
    assert _duplicate_type_label("same_content_duplicate") == t(
        "home.candidates.duplicate_type.same_content_duplicate"
    )
    assert _duplicate_type_label("") == t("home.candidates.duplicate_type.none")
    assert _duplicate_type_label("custom") == "custom"


def test_candidate_row_surfaces_duplicate_type_and_reason():
    row = _candidate_row(
        {
            "name": "report.txt",
            "recommendation": Recommendation.NEEDS_MANUAL_CHECK.value,
            "risk_level": "needs_manual_check",
            "duplicate_type": "same_name_candidate",
            "duplicate_reason": "same filename appears more than once",
            "candidate_reasons": ["duplicate candidate: same filename appears more than once"],
            "size_bytes": 42,
            "mtime": "2026-05-25T00:00:00+00:00",
            "path": "C:/scan/report.txt",
        }
    )

    assert row["duplicate_type"] == t("home.candidates.duplicate_type.same_name_candidate")
    assert row["duplicate_reason"] == "same filename appears more than once"
    assert "duplicate" in str(row["reasons"]).lower()


def test_render_home_candidate_metric_uses_candidate_count(monkeypatch):
    metric_values: list[tuple[str, object]] = []
    session_state = {
        "folder_scan_current": {
            "path": "C:/scan",
            "records": [
                {"name": "keep.txt", "path": "C:/scan/keep.txt", "candidate_reasons": []},
                {"name": "candidate-a.txt", "path": "C:/scan/candidate-a.txt", "candidate_reasons": ["stale"], "size_bytes": 1},
                {"name": "candidate-b.txt", "path": "C:/scan/candidate-b.txt", "candidate_reasons": ["large"], "size_bytes": 2},
            ],
            "stats": {
                "scanned_files": 3,
                "total_bytes": 3,
                "stale_candidates": 1,
                "large_candidates": 1,
            },
            "errors": [],
        },
        "folder_scan_options": {
            "stale_days": 30,
            "recursive": True,
            "max_files": 100,
            "large_file_bytes": 1024,
        },
        "folder_scan_path": "C:/scan",
    }

    fake_st = SimpleNamespace(
        session_state=session_state,
        markdown=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        columns=lambda spec, **kwargs: [_Column() for _ in range(spec if isinstance(spec, int) else len(spec))],
        text_input=lambda *args, **kwargs: "C:/scan",
        button=lambda *args, **kwargs: False,
        progress=lambda *args, **kwargs: SimpleNamespace(progress=lambda value: None),
        empty=lambda: SimpleNamespace(text=lambda value: None),
        expander=lambda *args, **kwargs: nullcontext(),
        write=lambda *args, **kwargs: None,
        subheader=lambda *args, **kwargs: None,
        checkbox=lambda *args, **kwargs: False,
        download_button=lambda *args, **kwargs: None,
        code=lambda *args, **kwargs: None,
        dataframe=lambda *args, **kwargs: None,
        multiselect=lambda *args, **kwargs: [],
        caption=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr("ui_home.st", fake_st)
    monkeypatch.setattr("ui_home.card_open", lambda *args, **kwargs: None)
    monkeypatch.setattr("ui_home.card_close", lambda *args, **kwargs: None)
    monkeypatch.setattr("ui_home.get_quarantine_items_safe", lambda _path: ([], []))
    monkeypatch.setattr("ui_home._render_candidate_editor", lambda _context, candidates: [str(item["path"]) for item in candidates])
    monkeypatch.setattr("ui_home._render_operation_results", lambda _result: None)
    monkeypatch.setattr("ui_home.resolve_report_inputs", lambda current_scan, report_snapshot, operation_result: (current_scan, operation_result))
    monkeypatch.setattr("ui_home.export_folder_report_markdown", lambda *_args, **_kwargs: "report")
    monkeypatch.setattr("ui_home.export_folder_report_csv", lambda *_args, **_kwargs: b"csv")
    monkeypatch.setattr(
        "ui_home.render_safe_html_text",
        lambda css_class, value, max_chars=200: metric_values.append((css_class, value)),
    )

    context = SimpleNamespace(storage=SimpleNamespace(path_exists=lambda path: False), processor=SimpleNamespace())
    render_home(context)

    candidate_metrics = [value for css_class, value in metric_values if css_class == "status-metric"]
    assert 2 in candidate_metrics


def test_limit_candidate_rows_caps_large_result_sets():
    candidates = [{"path": f"C:/scan/{index}.txt"} for index in range(620)]

    visible, hidden = limit_candidate_rows(candidates, limit=500)

    assert len(visible) == 500
    assert hidden == 120


def test_merge_visible_selection_preserves_hidden_rows():
    merged = merge_visible_selection(
        {"C:/scan/hidden.txt", "C:/scan/visible-old.txt"},
        [
            {"path": "C:/scan/visible-old.txt", "select": True},
            {"path": "C:/scan/visible-new.txt", "select": False},
        ],
        [
            {"path": "C:/scan/visible-old.txt", "select": False},
            {"path": "C:/scan/visible-new.txt", "select": True},
        ],
    )

    assert merged == {"C:/scan/hidden.txt", "C:/scan/visible-new.txt"}


def test_merge_visible_selection_clears_only_visible_rows():
    merged = merge_visible_selection(
        {"C:/scan/hidden.txt", "C:/scan/visible.txt"},
        [{"path": "C:/scan/visible.txt", "select": True}],
        [{"path": "C:/scan/visible.txt", "select": False}],
    )

    assert merged == {"C:/scan/hidden.txt"}
