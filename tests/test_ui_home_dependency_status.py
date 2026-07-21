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
    _current_primary_action_label,
    _current_settings_draft,
    _default_processing_options,
    _default_scan_options,
    _discard_settings_draft,
    _duplicate_type_label,
    _malware_primary_action_label,
    _maybe_auto_open_result_dialog,
    _open_settings_dialog,
    _render_candidate_editor,
    _render_home_dialogs,
    _reset_settings_draft_to_defaults,
    _save_settings_draft,
    _store_analysis_result,
    _store_malware_scan_result,
    cache_dependency_status,
    get_cached_dependency_status,
    limit_candidate_rows,
    merge_visible_selection,
    refresh_dependency_status,
    render_home,
    summarize_recommendations,
)
from ui_labels import recommendation_display_label, topic_display_label
from ui_state import (
    SESSION_AI_ENABLED,
    SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID,
    SESSION_FOLDER_ANALYSIS_DIALOG_OPEN,
    SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID,
    SESSION_FOLDER_LAST_OPERATION_RESULT,
    SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID,
    SESSION_FOLDER_MALWARE_DIALOG_OPEN,
    SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID,
    SESSION_FOLDER_MALWARE_SCAN_RESULT,
    SESSION_FOLDER_REPORT_SNAPSHOT,
    SESSION_FOLDER_RESTORE_RESULT,
    SESSION_FOLDER_SCAN_CURRENT,
    SESSION_FOLDER_SCAN_OPTIONS,
    SESSION_FOLDER_SCAN_OPTIONS_DRAFT,
    SESSION_FOLDER_SELECTED_PATHS,
    SESSION_FOLDER_SETTINGS_DIALOG_OPEN,
    SESSION_PROCESSING_OPTIONS,
)


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
            "malware_status": "infected",
            "malware_scanner": "ClamAV",
            "malware_threat_name": "Eicar-Test-Signature",
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
    assert row["malware_status"] == t("malware.scan_infected")
    assert row["malware_scanner"] == "ClamAV"
    assert row["malware_threat_name"] == "Eicar-Test-Signature"
    assert "duplicate" in str(row["reasons"]).lower()


def test_render_home_candidate_metric_uses_candidate_count(monkeypatch):
    candidate_metrics: list[int] = []
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
        container=lambda **kwargs: nullcontext(),
        selectbox=lambda _label, options, index=0, **kwargs: options[index],
        text_input=lambda *args, **kwargs: "C:/scan",
        button=lambda *args, **kwargs: False,
        progress=lambda *args, **kwargs: SimpleNamespace(progress=lambda value: None),
        empty=lambda: SimpleNamespace(text=lambda value: None),
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
    monkeypatch.setattr("ui_home.get_quarantine_items_safe", lambda _path: ([], []))
    monkeypatch.setattr(
        "ui_home._render_candidate_editor",
        lambda _context, candidates, **_kwargs: [str(item["path"]) for item in candidates],
    )
    monkeypatch.setattr("ui_home._render_operation_results", lambda _result: None)
    monkeypatch.setattr("ui_home.resolve_report_inputs", lambda current_scan, report_snapshot, operation_result: (current_scan, operation_result))
    monkeypatch.setattr("ui_home.export_folder_report_markdown", lambda *_args, **_kwargs: "report")
    monkeypatch.setattr("ui_home.export_folder_report_csv", lambda *_args, **_kwargs: b"csv")
    monkeypatch.setattr("ui_home._render_scan_metrics", lambda stats, candidates, quarantined: candidate_metrics.append(len(candidates)))

    context = SimpleNamespace(storage=SimpleNamespace(path_exists=lambda path: False), processor=SimpleNamespace())
    render_home(context)

    assert candidate_metrics == [2]


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


def test_candidate_editor_filters_not_scanned_when_malware_scan_enabled(monkeypatch):
    session_state = {
        "folder_selected_paths": ["C:/scan/not-scanned.txt", "C:/scan/clean.txt"],
    }
    fake_st = SimpleNamespace(
        session_state=session_state,
        info=lambda *args, **kwargs: None,
        caption=lambda *args, **kwargs: None,
        columns=lambda *args, **kwargs: [_Column(), _Column(), _Column(), _Column()],
        button=lambda *args, **kwargs: False,
        markdown=lambda *args, **kwargs: None,
        multiselect=lambda *args, **kwargs: ["C:/scan/not-scanned.txt", "C:/scan/clean.txt"],
        dataframe=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("ui_home.st", fake_st)

    selected = _render_candidate_editor(
        SimpleNamespace(pandas=None),
        [
            {"path": "C:/scan/not-scanned.txt", "name": "not-scanned.txt", "malware_status": "not_scanned"},
            {"path": "C:/scan/clean.txt", "name": "clean.txt", "malware_status": "clean"},
        ],
        enable_malware_scan=True,
    )

    assert selected == ["C:/scan/clean.txt"]


def test_candidate_editor_allows_not_scanned_when_malware_scan_disabled(monkeypatch):
    session_state = {
        "folder_selected_paths": ["C:/scan/not-scanned.txt", "C:/scan/clean.txt"],
    }
    fake_st = SimpleNamespace(
        session_state=session_state,
        info=lambda *args, **kwargs: None,
        caption=lambda *args, **kwargs: None,
        columns=lambda *args, **kwargs: [_Column(), _Column(), _Column(), _Column()],
        button=lambda *args, **kwargs: False,
        markdown=lambda *args, **kwargs: None,
        multiselect=lambda *args, **kwargs: ["C:/scan/not-scanned.txt", "C:/scan/clean.txt"],
        dataframe=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("ui_home.st", fake_st)

    selected = _render_candidate_editor(
        SimpleNamespace(pandas=None),
        [
            {"path": "C:/scan/not-scanned.txt", "name": "not-scanned.txt", "malware_status": "not_scanned"},
            {"path": "C:/scan/clean.txt", "name": "clean.txt", "malware_status": "clean"},
        ],
        enable_malware_scan=False,
    )

    assert selected == ["C:/scan/not-scanned.txt", "C:/scan/clean.txt"]


def test_settings_dialog_open_and_discard_behavior(monkeypatch):
    session_state = {
        SESSION_FOLDER_SCAN_OPTIONS: {"stale_days": 120, "recursive": False},
        SESSION_PROCESSING_OPTIONS: {"enable_pdf_preview": True, "enable_ocr": False},
        SESSION_AI_ENABLED: True,
    }

    monkeypatch.setattr("ui_home.st.session_state", session_state)

    _open_settings_dialog()

    assert session_state[SESSION_FOLDER_SETTINGS_DIALOG_OPEN] is True
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT]["stale_days"] == 120
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT]["enable_pdf_preview"] is True
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT]["ai_enabled"] is True

    session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT]["stale_days"] = 999
    _discard_settings_draft()

    assert session_state[SESSION_FOLDER_SETTINGS_DIALOG_OPEN] is False
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT]["stale_days"] == 120


def test_save_settings_applies_values_atomically(monkeypatch):
    session_state = {
        SESSION_FOLDER_SCAN_OPTIONS: _default_scan_options(),
        SESSION_PROCESSING_OPTIONS: _default_processing_options(),
        SESSION_AI_ENABLED: False,
        SESSION_FOLDER_SCAN_OPTIONS_DRAFT: {},
        SESSION_FOLDER_SETTINGS_DIALOG_OPEN: True,
    }
    context = SimpleNamespace(processor=SimpleNamespace(pdf_preview_max_pages=2, pdf_ocr_max_pages=4))

    monkeypatch.setattr("ui_home.st.session_state", session_state)

    _save_settings_draft(
        {
            "stale_days": 45,
            "large_file_bytes": 512,
            "recursive": False,
            "max_files": 777,
            "duplicate_detection": True,
            "enable_malware_scan": True,
            "malware_scan_mode": "full",
            "malware_scan_policy": "strict",
            "malware_scan_timeout_seconds": 90,
            "malware_database_max_age_days": 3,
            "ai_enabled": True,
            "enable_pdf_preview": True,
            "enable_ocr": True,
        },
        context=context,
    )

    assert session_state[SESSION_FOLDER_SCAN_OPTIONS]["stale_days"] == 45
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS]["large_file_bytes"] == 512 * 1024 * 1024
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS]["recursive"] is False
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS]["max_files"] == 777
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS]["duplicate_detection"] is True
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS]["enable_malware_scan"] is True
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS]["malware_scan_mode"] == "full"
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS]["malware_scan_policy"] == "strict"
    assert session_state[SESSION_AI_ENABLED] is True
    assert session_state[SESSION_PROCESSING_OPTIONS]["enable_pdf_preview"] is True
    assert session_state[SESSION_PROCESSING_OPTIONS]["enable_ocr"] is True
    assert session_state[SESSION_FOLDER_SETTINGS_DIALOG_OPEN] is False
    assert session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT]["stale_days"] == 45


def test_reset_settings_restores_defaults(monkeypatch):
    session_state = {
        SESSION_FOLDER_SCAN_OPTIONS_DRAFT: {"stale_days": 45, "enable_pdf_preview": True, "ai_enabled": True}
    }

    monkeypatch.setattr("ui_home.st.session_state", session_state)

    _reset_settings_draft_to_defaults()

    assert session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT] == {
        **_default_scan_options(),
        "ai_enabled": False,
        "enable_pdf_preview": False,
        "enable_ocr": False,
    }


def test_settings_persist_across_rerun_reads(monkeypatch):
    session_state = {
        SESSION_FOLDER_SCAN_OPTIONS: {"stale_days": 88, "recursive": False},
        SESSION_PROCESSING_OPTIONS: {"enable_pdf_preview": True, "enable_ocr": True},
        SESSION_AI_ENABLED: True,
    }

    monkeypatch.setattr("ui_home.st.session_state", session_state)

    draft = _current_settings_draft()

    assert draft["stale_days"] == 88
    assert draft["recursive"] is False
    assert draft["enable_pdf_preview"] is True
    assert draft["enable_ocr"] is True
    assert draft["ai_enabled"] is True


def test_primary_action_labels_change_with_settings():
    assert _malware_primary_action_label({"enable_malware_scan": False}) == t("home.scan.primary_action_organization")
    assert _malware_primary_action_label({"enable_malware_scan": True}) == t("home.scan.primary_action_secure")
    assert _malware_primary_action_label({"malware_only_operation": True}) == t("home.scan.primary_action_malware_only")


def test_current_primary_action_label_matches_requested_modes():
    assert _current_primary_action_label({"enable_malware_scan": False}) == t("home.scan.primary_action_organization")
    assert _current_primary_action_label({"enable_malware_scan": True}) == t("home.scan.primary_action_secure")
    assert _current_primary_action_label({"malware_only_operation": True}) == t("home.scan.primary_action_malware_only")


def test_auto_open_result_dialog_opens_once_and_respects_dismissed(monkeypatch):
    session_state = {
        SESSION_FOLDER_MALWARE_DIALOG_OPEN: False,
        SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID: "mal-1",
        SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID: "",
    }

    monkeypatch.setattr("ui_home.st.session_state", session_state)

    _maybe_auto_open_result_dialog(
        result={"result_id": "mal-1"},
        dialog_key=SESSION_FOLDER_MALWARE_DIALOG_OPEN,
        auto_open_key=SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID,
        dismissed_key=SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID,
    )

    assert session_state[SESSION_FOLDER_MALWARE_DIALOG_OPEN] is True
    assert session_state[SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID] is None

    session_state[SESSION_FOLDER_MALWARE_DIALOG_OPEN] = False
    session_state[SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID] = "mal-1"
    session_state[SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID] = "mal-1"

    _maybe_auto_open_result_dialog(
        result={"result_id": "mal-1"},
        dialog_key=SESSION_FOLDER_MALWARE_DIALOG_OPEN,
        auto_open_key=SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID,
        dismissed_key=SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID,
    )

    assert session_state[SESSION_FOLDER_MALWARE_DIALOG_OPEN] is False
    assert session_state[SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID] is None


def test_store_result_helpers_prepare_dialog_and_persist_state(monkeypatch):
    session_state = {
        SESSION_FOLDER_MALWARE_SCAN_RESULT: None,
        SESSION_FOLDER_SCAN_CURRENT: None,
        SESSION_FOLDER_REPORT_SNAPSHOT: None,
        SESSION_FOLDER_LAST_OPERATION_RESULT: {"stale": True},
        SESSION_FOLDER_RESTORE_RESULT: {"stale": True},
        SESSION_FOLDER_SELECTED_PATHS: ["C:/scan/old.txt"],
        SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID: None,
        SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID: "previous-analysis",
        SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID: None,
        SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID: "previous-malware",
    }

    monkeypatch.setattr("ui_home.st.session_state", session_state)
    monkeypatch.setattr("ui_home.build_report_snapshot", lambda result: {"path": result["path"], "count": len(result["records"])})

    malware_result = {
        "result_id": "malware-1",
        "path": "C:/scan",
        "records": [
            {
                "path": "C:/scan/old.txt",
                "malware_status": "clean",
                "malware_scan_health": "ok",
                "malware_backend": "clamav",
                "malware_engine_version": "1.0",
                "malware_database_version": "123",
                "malware_database_date": "2026-07-20",
                "malware_scanned_at": "2026-07-20T10:00:00+00:00",
                "malware_cache_hit": False,
                "malware_policy_name": "standard",
                "malware_policy_version": "standard-v1",
                "malware_file_sha256": "abc",
                "malware_file_size": 4,
                "malware_file_mtime_ns": 1,
                "malware_file_inode": 2,
            }
        ],
        "summary": {},
    }
    _store_malware_scan_result(
        {
            "enable_malware_scan": True,
            "malware_scan_policy": "standard",
            "malware_database_max_age_days": 7,
        },
        malware_result,
    )

    assert session_state[SESSION_FOLDER_MALWARE_SCAN_RESULT]["result_id"] == "malware-1"
    assert session_state[SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID] == "malware-1"
    assert session_state[SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID] == ""

    analysis_result = {
        "result_id": "analysis-1",
        "path": "C:/scan",
        "records": [
            {
                "path": "C:/scan/old.txt",
                "name": "old.txt",
                "candidate_reasons": ["stale"],
                "size_bytes": 4,
                "mtime": "2026-07-20T10:00:00+00:00",
            }
        ],
        "stats": {"scanned_files": 1, "total_bytes": 4, "stale_candidates": 1, "large_candidates": 0},
    }
    _store_analysis_result(
        {
            "enable_malware_scan": True,
            "malware_scan_policy": "standard",
            "malware_database_max_age_days": 7,
        },
        analysis_result,
    )

    assert session_state[SESSION_FOLDER_SCAN_CURRENT]["result_id"] == "analysis-1"
    assert session_state[SESSION_FOLDER_REPORT_SNAPSHOT] == {"path": "C:/scan", "count": 1}
    assert session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] is None
    assert session_state[SESSION_FOLDER_RESTORE_RESULT] is None
    assert session_state[SESSION_FOLDER_SELECTED_PATHS] == []
    assert session_state[SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID] == "analysis-1"
    assert session_state[SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID] == ""


def test_result_dialogs_use_large_width(monkeypatch, tmp_path):
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "ui_home.render_dialog",
        lambda **kwargs: captured.append((kwargs["key"], kwargs.get("width", "small"))),
    )

    context = SimpleNamespace(
        processor=SimpleNamespace(),
        storage=SimpleNamespace(),
        project_root=tmp_path,
        upload_dir=tmp_path / "uploads",
        repo_root=tmp_path,
        db_path=tmp_path / "app.db",
        max_upload_bytes=1024,
    )

    _render_home_dialogs(context)

    widths = dict(captured)
    assert widths[SESSION_FOLDER_MALWARE_DIALOG_OPEN] == "large"
    assert widths[SESSION_FOLDER_ANALYSIS_DIALOG_OPEN] == "large"
