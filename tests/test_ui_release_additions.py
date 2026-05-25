from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import app_main
import ui_records
import ui_renderers
import ui_review
from i18n import t
from services import AnalysisResult
from ui_common import UIContext


def _noop(*args, **kwargs):  # noqa: ANN001, ANN002
    return None


class _SessionState(dict):
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value) -> None:
        self[name] = value


def test_render_review_confirms_selected_topics_and_saved_summaries(monkeypatch):
    successes: list[str] = []
    build_calls: list[dict[str, object]] = []
    session_state = _SessionState(
        {
            "analysis_results": [
                AnalysisResult(
                    file_id=7,
                    original_name="invoice.pdf",
                    file_type="document",
                    standard_date="2026-05-18",
                    main_topic="Bills",
                    suggested_main_topic="Bills",
                    tag_scores={"Bills": 0.9},
                    classification_reason="rule",
                    final_decision_reason="rule",
                    metadata={
                        "file_type": "document",
                        "standard_date": "2026-05-18",
                        "extracted_text": "",
                        "is_scanned": False,
                        "preview_path": None,
                        "ocr_error": None,
                        "notes": ["dry-run preview ready"],
                    },
                    preview_path=None,
                    is_scanned=False,
                    summary="old summary",
                )
            ],
            "review_summaries": {7: "approved summary"},
            "ai_enabled": False,
        }
    )
    fake_st = SimpleNamespace(
        session_state=session_state,
        header=_noop,
        info=_noop,
        error=_noop,
        markdown=_noop,
        expander=lambda *args, **kwargs: nullcontext(),
        columns=lambda sizes: (nullcontext(), nullcontext()),
        subheader=_noop,
        image=_noop,
        warning=_noop,
        caption=_noop,
        json=_noop,
        write=_noop,
        selectbox=lambda label, options, index=0, key=None: "Archive",
        button=lambda label, **kwargs: label == t("review.confirm_button"),
        code=_noop,
        success=lambda value: successes.append(str(value)),
    )
    monkeypatch.setattr(ui_review, "st", fake_st)
    monkeypatch.setattr(ui_review, "is_debug", lambda: False)

    def _build_confirmed_results(analysis_results, processor, selected_topics, summaries):  # noqa: ANN001
        build_calls.append(
            {
                "selected_topics": dict(selected_topics),
                "summaries": dict(summaries),
            }
        )
        return ["confirmed"]

    monkeypatch.setattr(
        ui_review,
        "apply_manual_topic_override",
        lambda result, processor, chosen_topic, summary: result,
    )
    monkeypatch.setattr(
        ui_review,
        "build_confirmed_results",
        _build_confirmed_results,
    )

    ui_review.render_review(
        cast(
            UIContext,
            SimpleNamespace(storage=SimpleNamespace(path_exists=lambda path: False), processor=object()),
        )
    )

    assert build_calls == [{"selected_topics": {7: "Archive"}, "summaries": {7: "approved summary"}}]
    assert session_state.confirmed_results == ["confirmed"]
    assert successes == [t("review.confirm_success")]


def test_render_records_reclassify_missing_file_surfaces_specific_error(monkeypatch):
    errors: list[str] = []
    select_values = iter(
        [
            t("search_records.records_filters.all"),
            t("search_records.records_filters.all"),
            t("search_records.records_filters.all"),
            25,
            3,
        ]
    )
    button_values = iter([False, False, True])
    fake_st = SimpleNamespace(
        session_state={},
        header=_noop,
        columns=lambda sizes: tuple(nullcontext() for _ in range(sizes if isinstance(sizes, int) else len(sizes))),
        selectbox=lambda *args, **kwargs: next(select_values),
        date_input=lambda *args, **kwargs: None,
        text_input=lambda *args, **kwargs: "",
        number_input=lambda *args, **kwargs: 1,
        info=_noop,
        caption=_noop,
        dataframe=_noop,
        subheader=_noop,
        button=lambda *args, **kwargs: next(button_values),
        spinner=lambda *args, **kwargs: nullcontext(),
        error=lambda value: errors.append(str(value)),
        success=_noop,
        download_button=_noop,
    )
    monkeypatch.setattr(ui_records, "st", fake_st)
    monkeypatch.setattr(
        ui_records,
        "reclassify_record",
        lambda **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    storage = SimpleNamespace(
        get_record_filter_values=lambda: {"status": [], "main_topic": [], "file_type": []},
        get_records_page=lambda **kwargs: {
            "items": [{"file_id": 3, "original_name": "missing.pdf", "created_at": "2026-05-18T00:00:00"}],
            "total": 1,
        },
    )

    ui_records.render_records(cast(UIContext, SimpleNamespace(storage=storage, pandas=None, processor=object())))

    assert errors == [t("search_records.reclassify_missing_file")]


def test_render_records_normal_state_shows_exports_and_page_caption(monkeypatch):
    captions: list[str] = []
    downloads: list[str] = []
    select_values = iter(
        [
            t("search_records.records_filters.all"),
            t("search_records.records_filters.all"),
            t("search_records.records_filters.all"),
            25,
            9,
        ]
    )
    fake_st = SimpleNamespace(
        session_state={},
        header=_noop,
        columns=lambda sizes: tuple(nullcontext() for _ in range(sizes if isinstance(sizes, int) else len(sizes))),
        selectbox=lambda *args, **kwargs: next(select_values),
        date_input=lambda *args, **kwargs: None,
        text_input=lambda *args, **kwargs: "",
        number_input=lambda *args, **kwargs: 1,
        info=_noop,
        caption=lambda value: captions.append(str(value)),
        dataframe=_noop,
        subheader=_noop,
        button=lambda *args, **kwargs: False,
        spinner=lambda *args, **kwargs: nullcontext(),
        success=_noop,
        error=_noop,
        download_button=lambda label, *args, **kwargs: downloads.append(label),
    )
    monkeypatch.setattr(ui_records, "st", fake_st)

    storage = SimpleNamespace(
        get_record_filter_values=lambda: {"status": ["READY"], "main_topic": ["Bills"], "file_type": ["document"]},
        get_records_page=lambda **kwargs: {
            "items": [
                {
                    "file_id": 9,
                    "original_name": "receipt.pdf",
                    "file_type": "document",
                    "standard_date": "2026-05-18",
                    "main_topic": "Bills",
                    "all_tags": "Bills",
                    "status": "READY",
                    "manual_override": 0,
                    "last_error": None,
                    "created_at": "2026-05-18T08:00:00",
                }
            ],
            "total": 1,
        },
    )

    ui_records.render_records(cast(UIContext, SimpleNamespace(storage=storage, pandas=None, processor=object())))

    assert any(t("search_records.records_showing_page", current_page=1, page_count=1, total=1) in caption for caption in captions)
    assert downloads == [t("search_records.records_export_csv"), t("search_records.records_export_md")]


def test_render_dependency_status_empty_sections_show_captions(monkeypatch):
    captions: list[str] = []
    writes: list[str] = []
    fake_st = SimpleNamespace(
        write=lambda value: writes.append(str(value)),
        json=_noop,
        caption=lambda value: captions.append(str(value)),
    )
    monkeypatch.setattr(ui_renderers, "st", fake_st)

    ui_renderers.render_dependency_status({})

    assert len(writes) == 3
    assert len(captions) == 3


def test_build_context_handles_missing_optional_dependencies(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        app_main,
        "_bootstrap_services",
        lambda: (SimpleNamespace(), SimpleNamespace()),
    )
    monkeypatch.setattr(app_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app_main, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(app_main, "REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(app_main, "DB_PATH", tmp_path / "app.db")
    monkeypatch.setattr(app_main, "MAX_UPLOAD_BYTES", 1234)
    monkeypatch.setattr(app_main, "_optional_import", lambda module_name: None)

    context = app_main._build_context()

    assert context.pandas is None
    assert context.plt is None
    assert context.project_root == tmp_path
    assert context.max_upload_bytes == 1234
