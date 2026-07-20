from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

from i18n import t
from ui_common import render_dialog
from ui_home import _render_home_header, render_home


class _Column:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_render_home_header_shows_dialog_buttons(monkeypatch):
    button_labels: list[str] = []
    fake_st = SimpleNamespace(
        session_state={},
        markdown=lambda *args, **kwargs: None,
        columns=lambda spec, **kwargs: [_Column() for _ in range(len(spec))],
        selectbox=lambda _label, options, index=0, **kwargs: options[index],
        button=lambda label, **kwargs: button_labels.append(label) or False,
    )

    monkeypatch.setattr("ui_home.st", fake_st)

    _render_home_header()

    assert button_labels == [
        t("home.settings.open_button"),
        t("home.dialogs.help_button"),
        t("home.dialogs.safety_button"),
        t("home.dialogs.workflow_button"),
    ]


def test_render_home_does_not_render_process_steps_until_dialog_opens(monkeypatch):
    calls: list[str] = []
    fake_st = SimpleNamespace(
        session_state={"folder_scan_options": {}, "folder_scan_path": ""},
        markdown=lambda *args, **kwargs: None,
        columns=lambda spec, **kwargs: [_Column() for _ in range(spec if isinstance(spec, int) else len(spec))],
        button=lambda *args, **kwargs: False,
        container=lambda **kwargs: nullcontext(),
        selectbox=lambda _label, options, index=0, **kwargs: options[index],
        text_input=lambda *args, **kwargs: "",
        caption=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        subheader=lambda *args, **kwargs: None,
        checkbox=lambda *args, **kwargs: False,
    )

    monkeypatch.setattr("ui_home.st", fake_st)
    monkeypatch.setattr("ui_home._render_process_steps", lambda: calls.append("process"))

    render_home(SimpleNamespace())

    assert calls == []


def test_render_dialog_fallback_closes_without_streamlit_dialog(monkeypatch):
    session_state = {"dialog_demo": True}
    render_body_calls: list[str] = []
    button_keys: list[str] = []
    fake_st = SimpleNamespace(
        session_state=session_state,
        expander=lambda *args, **kwargs: nullcontext(),
        button=lambda label, key=None, **kwargs: button_keys.append(str(key)) or True,
        rerun=lambda: render_body_calls.append("rerun"),
    )

    monkeypatch.setattr("ui_common.st", fake_st)

    render_dialog(
        key="dialog_demo",
        title="Dialog Demo",
        render_body=lambda: render_body_calls.append("body"),
    )

    assert render_body_calls == ["body", "rerun"]
    assert button_keys == ["dialog_demo_close_fallback"]
    assert session_state["dialog_demo"] is False
