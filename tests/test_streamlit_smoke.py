from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import app_main
import ui_home
import ui_state
from i18n import DEFAULT_LANGUAGE, t
from ui_common import UIContext


def _noop(*args, **kwargs):  # noqa: ANN001, ANN002
    return None


class _SessionState(dict):
    def __getattr__(self, name: str):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


class _Sidebar:
    def __init__(self, parent: _FakeStreamlit) -> None:
        self.parent = parent

    def header(self, value: str) -> None:
        self.parent.calls.append(("sidebar.header", value))

    def markdown(self, value: str) -> None:
        self.parent.calls.append(("sidebar.markdown", value))

    def caption(self, value: str) -> None:
        self.parent.calls.append(("sidebar.caption", value))

    def expander(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.parent.calls.append(("sidebar.expander", args[0] if args else ""))
        return nullcontext()

    def selectbox(self, label: str, options, index=0, format_func=None, key=None):  # noqa: ANN001, ANN003
        del format_func
        self.parent.calls.append(("sidebar.selectbox", label))
        value = options[index]
        if key:
            self.parent.session_state[key] = value
        return value


class _FakeStreamlit:
    def __init__(self) -> None:
        self.session_state = _SessionState()
        self.calls: list[tuple[str, object]] = []
        self.sidebar = _Sidebar(self)

    def set_page_config(self, **kwargs) -> None:  # noqa: ANN003
        self.calls.append(("set_page_config", kwargs))

    def tabs(self, labels: list[str]):
        self.calls.append(("tabs", tuple(labels)))
        return tuple(nullcontext() for _ in labels)

    def columns(self, value, **kwargs):  # noqa: ANN001, ANN003
        count = value if isinstance(value, int) else len(value)
        return tuple(nullcontext() for _ in range(count))

    def button(self, label: str, **kwargs) -> bool:  # noqa: ANN003
        self.calls.append(("button", label))
        return label == t("sidebar.check_dependencies")

    def checkbox(self, label: str, value: bool = False, **kwargs) -> bool:  # noqa: ANN003
        self.calls.append(("checkbox", label))
        return value

    def toggle(self, label: str, value: bool = False, **kwargs) -> bool:  # noqa: ANN003
        self.calls.append(("toggle", label))
        return value

    def slider(self, _label: str, _min, _max, value, **kwargs):  # noqa: ANN001, ANN003
        return value

    def number_input(self, _label: str, **kwargs):  # noqa: ANN003
        return kwargs.get("value", 1)

    def markdown(self, value: str, **kwargs) -> None:  # noqa: ANN003
        self.calls.append(("markdown", value))

    def caption(self, value: str) -> None:
        self.calls.append(("caption", value))

    def expander(self, label: str, **kwargs):  # noqa: ANN003
        self.calls.append(("expander", label))
        return nullcontext()

    def success(self, value: str) -> None:
        self.calls.append(("success", value))

    def json(self, value: object) -> None:
        self.calls.append(("json", value))

    def header(self, value: str) -> None:
        self.calls.append(("header", value))

    def divider(self) -> None:
        self.calls.append(("divider", None))


def test_app_entrypoints_are_importable():
    assert callable(app_main.main)


def test_page_config_smoke(monkeypatch):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(app_main, "st", fake_st)
    monkeypatch.setattr(app_main, "inject_browser_storage_sanitizer", _noop)
    monkeypatch.setattr(app_main, "setup_logging", _noop)

    app_main._configure_page()

    assert ("set_page_config", {"page_title": t("app.page_title", lang=DEFAULT_LANGUAGE), "layout": "wide"}) in fake_st.calls


def test_session_state_defaults_are_initialized_without_existing_keys(monkeypatch):
    fake_st = SimpleNamespace(session_state=_SessionState())
    monkeypatch.setattr(ui_state, "st", fake_st)

    ui_state.init_session_state()

    assert fake_st.session_state["analysis_results"] == []
    assert fake_st.session_state["review_summaries"] == {}
    assert fake_st.session_state["processing_options"]["enable_ocr"] is False


def test_app_main_renders_tabs_with_mocked_sections(monkeypatch, tmp_path: Path):
    fake_st = _FakeStreamlit()
    rendered: list[str] = []
    context = SimpleNamespace(
        processor=SimpleNamespace(get_dependency_status=lambda: {"system": {"ffmpeg": False}}),
        storage=SimpleNamespace(),
        project_root=tmp_path,
        upload_dir=tmp_path / "uploads",
        repo_root=tmp_path / "repo",
        db_path=tmp_path / "app.db",
        max_upload_bytes=1024,
        pandas=None,
        plt=None,
    )
    monkeypatch.setattr(app_main, "st", fake_st)
    monkeypatch.setattr(app_main, "_build_context", lambda: context)
    monkeypatch.setattr(app_main, "inject_browser_storage_sanitizer", _noop)
    monkeypatch.setattr(app_main, "setup_logging", _noop)
    monkeypatch.setattr(app_main, "inject_global_css", lambda: rendered.append("css"))
    monkeypatch.setattr(app_main, "init_session_state", lambda: rendered.append("state"))
    monkeypatch.setattr(app_main, "render_sidebar", lambda _ctx: rendered.append("sidebar"))
    monkeypatch.setattr(app_main, "render_home", lambda _ctx: rendered.append("home"))
    monkeypatch.setattr(app_main, "render_upload", lambda _ctx: rendered.append("upload"))
    monkeypatch.setattr(app_main, "render_review", lambda _ctx: rendered.append("review"))
    monkeypatch.setattr(app_main, "render_execute", lambda _ctx: rendered.append("execute"))
    monkeypatch.setattr(app_main, "render_search", lambda _ctx, show_header=False: rendered.append("search"))
    monkeypatch.setattr(app_main, "render_records", lambda _ctx, show_header=False: rendered.append("records"))

    app_main.main()

    assert ("tabs", tuple(app_main.get_main_tab_labels())) in fake_st.calls
    assert rendered == ["css", "state", "sidebar", "home", "upload", "review", "execute", "search", "records"]


def test_sidebar_dependency_fallback_smoke(monkeypatch, tmp_path: Path):
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(ui_home, "st", fake_st)
    monkeypatch.setattr(ui_home, "render_dependency_status", lambda status: fake_st.calls.append(("deps", status)))
    context = cast(
        UIContext,
        SimpleNamespace(
        processor=SimpleNamespace(
            pdf_ocr_max_pages=3,
            pdf_preview_max_pages=1,
            get_dependency_status=lambda: {
                "python": {"pdf2image": False, "pytesseract": False},
                "system": {"ffmpeg": False},
                "config": {"poppler_path": False},
            },
        ),
        project_root=tmp_path,
        upload_dir=tmp_path / "uploads",
        repo_root=tmp_path / "repo",
        db_path=tmp_path / "app.db",
        max_upload_bytes=1024,
        ),
    )

    ui_home.render_sidebar(context)

    assert ("success", t("sidebar.dependency_check_success")) in fake_st.calls
    assert any(
        call[0] == "deps"
        and isinstance(call[1], dict)
        and call[1]["system"]["ffmpeg"] is False
        for call in fake_st.calls
    )
