from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import ui_records
import ui_search
import ui_upload


def _noop(*args, **kwargs):  # noqa: ANN001, ANN002
    return None


def _columns(count: int):
    return tuple(nullcontext() for _ in range(count))


class _ProgressRecorder:
    def progress(self, value: float) -> None:
        del value


class _TextRecorder:
    def text(self, value: str) -> None:
        del value


class _SessionState(dict):
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value) -> None:
        self[name] = value


def test_render_upload_handles_empty_selection(monkeypatch):
    infos: list[str] = []
    fake_st = SimpleNamespace(
        header=_noop,
        markdown=_noop,
        caption=_noop,
        file_uploader=lambda *args, **kwargs: [],
        info=lambda value: infos.append(str(value)),
    )
    monkeypatch.setattr(ui_upload, "st", fake_st)

    ui_upload.render_upload(SimpleNamespace())

    assert infos


def test_render_upload_surfaces_errors_duplicates_and_empty_results(monkeypatch):
    infos: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    successes: list[str] = []
    fake_st = SimpleNamespace(
        session_state=_SessionState(),
        header=_noop,
        markdown=_noop,
        caption=_noop,
        file_uploader=lambda *args, **kwargs: [
            SimpleNamespace(name="invoice.pdf", getbuffer=lambda: b"x", type="application/pdf")
        ],
        info=lambda value: infos.append(str(value)),
        success=lambda value: successes.append(str(value)),
        warning=lambda value: warnings.append(str(value)),
        error=lambda value: errors.append(str(value)),
        button=lambda *args, **kwargs: True,
        progress=lambda value=0: _ProgressRecorder(),
        empty=lambda: _TextRecorder(),
    )
    monkeypatch.setattr(ui_upload, "st", fake_st)
    monkeypatch.setattr(ui_upload, "reset_review_state", lambda: None)
    monkeypatch.setattr(
        ui_upload,
        "analyze_upload_batch",
        lambda *args, **kwargs: SimpleNamespace(
            results=[],
            errors=["bad upload"],
            duplicates=[SimpleNamespace(display="duplicate found")],
        ),
    )

    ui_upload.render_upload(SimpleNamespace(processor=object(), storage=object()))

    assert successes
    assert errors == ["bad upload"]
    assert warnings
    assert infos


def test_render_search_empty_query_shows_info(monkeypatch):
    infos: list[str] = []
    fake_st = SimpleNamespace(
        header=_noop,
        text_input=lambda *args, **kwargs: "",
        info=lambda value: infos.append(str(value)),
    )
    monkeypatch.setattr(ui_search, "st", fake_st)

    ui_search.render_search(SimpleNamespace(storage=object()))

    assert infos


def test_render_search_no_results_shows_info(monkeypatch):
    infos: list[str] = []
    fake_st = SimpleNamespace(
        header=_noop,
        text_input=lambda *args, **kwargs: "invoice",
        spinner=lambda *args, **kwargs: nullcontext(),
        info=lambda value: infos.append(str(value)),
        success=_noop,
    )
    monkeypatch.setattr(ui_search, "st", fake_st)

    ui_search.render_search(SimpleNamespace(storage=SimpleNamespace(search_content=lambda query: [])))

    assert infos


def test_render_records_empty_results_show_reset_hint(monkeypatch):
    infos: list[str] = []
    captions: list[str] = []
    select_values = iter(["All", "All", "All", 25])
    fake_st = SimpleNamespace(
        header=_noop,
        columns=lambda sizes: _columns(sizes if isinstance(sizes, int) else len(sizes)),
        selectbox=lambda *args, **kwargs: next(select_values),
        date_input=lambda *args, **kwargs: None,
        text_input=lambda *args, **kwargs: "invoice",
        number_input=lambda *args, **kwargs: 1,
        info=lambda value: infos.append(str(value)),
        caption=lambda value: captions.append(str(value)),
        dataframe=_noop,
        subheader=_noop,
        button=lambda *args, **kwargs: False,
        spinner=lambda *args, **kwargs: nullcontext(),
    )
    monkeypatch.setattr(ui_records, "st", fake_st)

    storage = SimpleNamespace(
        get_record_filter_values=lambda: {"status": [], "main_topic": [], "file_type": []},
        get_records_page=lambda **kwargs: {"items": [], "total": 0},
    )

    ui_records.render_records(SimpleNamespace(storage=storage, pandas=None, processor=object()))

    assert infos == ["No records match the current filters."]
    assert "Reset filters or clear search to bring records back into view." in captions


def test_render_records_refresh_failure_uses_ui_error_handler(monkeypatch):
    handled: list[tuple[str, str]] = []
    select_values = iter(["All", "All", "All", 25])
    button_values = iter([True, False, False])
    fake_st = SimpleNamespace(
        header=_noop,
        columns=lambda sizes: _columns(sizes if isinstance(sizes, int) else len(sizes)),
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
    )
    monkeypatch.setattr(ui_records, "st", fake_st)
    monkeypatch.setattr(
        ui_records,
        "handle_ui_exception",
        lambda message, exc: handled.append((message, str(exc))),
    )

    storage = SimpleNamespace(
        get_record_filter_values=lambda: {"status": [], "main_topic": [], "file_type": []},
        get_records_page=lambda **kwargs: {"items": [], "total": 0},
        refresh_file_locations=lambda fix_moving=True: (_ for _ in ()).throw(RuntimeError("refresh failed")),
    )

    ui_records.render_records(SimpleNamespace(storage=storage, pandas=None, processor=object()))

    assert handled == [("Failed to refresh file locations.", "refresh failed")]
