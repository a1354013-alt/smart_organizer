from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from types import SimpleNamespace

from i18n import t
from ui_common import render_dialog, reset_dialog_render_cycle
from ui_home import (
    _is_incomplete_malware_row,
    _malware_result_conclusion,
    _render_home_header,
    _render_malware_result_dialog_body,
    render_home,
)


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
    reset_dialog_render_cycle()
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


def test_render_dialog_passes_width_and_updates_session_state_on_dismiss(monkeypatch):
    reset_dialog_render_cycle()
    session_state = {"dialog_demo": True, "dialog_cleanup": "keep"}
    captured: dict[str, object] = {}

    def fake_dialog(title, *, width="small", dismissible=True, on_dismiss=None, **kwargs):  # noqa: ANN001, ANN003
        captured["title"] = title
        captured["kwargs"] = {
            **kwargs,
            "width": width,
            "dismissible": dismissible,
            "on_dismiss": on_dismiss,
        }

        def decorator(func):
            func()
            return func

        return decorator

    fake_st = SimpleNamespace(
        session_state=session_state,
        dialog=fake_dialog,
        container=lambda **kwargs: nullcontext(),
        button=lambda *args, **kwargs: False,
    )
    monkeypatch.setattr("ui_common.st", fake_st)

    render_dialog(
        key="dialog_demo",
        title="Dialog Demo",
        width="large",
        render_body=lambda: None,
        on_dismiss=lambda: session_state.__setitem__("dismissed", True),
        dismiss_state_keys=("dialog_cleanup",),
    )

    dismiss_callback = captured["kwargs"]["on_dismiss"]
    dismiss_callback()

    assert captured["kwargs"]["width"] == "large"
    assert session_state["dialog_demo"] is False
    assert session_state["dialog_cleanup"] is None
    assert session_state["dismissed"] is True


def test_malware_conclusion_avoids_all_clean_for_partial_or_truncated_coverage():
    incomplete = _malware_result_conclusion(
        {
            "infected_files": 0,
            "suspicious_files": 0,
            "incomplete_files": 0,
            "missing_result_files": 0,
            "coverage_is_partial": True,
            "limit_reached": False,
        }
    )
    truncated = _malware_result_conclusion(
        {
            "infected_files": 0,
            "suspicious_files": 0,
            "incomplete_files": 0,
            "missing_result_files": 0,
            "coverage_is_partial": False,
            "limit_reached": True,
        }
    )

    assert "clean" not in incomplete.lower()
    assert "clean" not in truncated.lower()


def test_is_incomplete_malware_row_excludes_mode_excluded():
    assert _is_incomplete_malware_row({"malware_scan_health": "incomplete"}) is True
    assert _is_incomplete_malware_row({"malware_scan_health": "error"}) is True
    assert _is_incomplete_malware_row({"malware_scan_health": "ok"}) is False
    assert _is_incomplete_malware_row({"malware_scan_health": "mode_excluded"}) is False


class _Tab:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _Expander:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def test_render_malware_result_dialog_excludes_mode_excluded_from_incomplete_and_shows_metric(monkeypatch):
    session_state = {
        "folder_malware_scan_result": {
            "scan_mode": "fast",
            "coverage_scope": "executables only",
            "recursive": False,
            "max_files": 10,
            "path": "C:/scan-root",
            "scanned_at": "2026-07-25T12:00:00+00:00",
            "summary": {
                "enumerated_files": 3,
                "files_in_scope": 1,
                "completed_files": 1,
                "clean_files": 1,
                "suspicious_files": 0,
                "infected_files": 0,
                "mode_excluded_files": 1,
                "incomplete_files": 1,
                "cache_hits": 0,
                "files_sent_to_scanner": 1,
                "total_bytes": 3,
                "elapsed_seconds": 0.5,
                "bytes_per_second": 6.0,
                "files_per_second": 2.0,
                "limit_reached": False,
                "coverage_is_partial": True,
                "overall_severity": "warning",
                "overall_status": "warning",
                "totals_consistent": True,
            },
            "records": [
                {
                    "name": "clean.exe",
                    "path": "C:/scan-root/clean.exe",
                    "malware_status": "clean",
                    "malware_scan_health": "ok",
                    "malware_cache_hit": False,
                    "malware_scanned_at": "2026-07-25T12:00:00+00:00",
                },
                {
                    "name": "skip.txt",
                    "path": "C:/scan-root/skip.txt",
                    "malware_status": "not_scanned",
                    "malware_scan_health": "mode_excluded",
                    "malware_message": "excluded by mode",
                    "malware_cache_hit": False,
                    "malware_scanned_at": "2026-07-25T12:00:00+00:00",
                },
                {
                    "name": "missing.bin",
                    "path": "C:/scan-root/missing.bin",
                    "malware_status": "not_scanned",
                    "malware_scan_health": "incomplete",
                    "malware_message": "scanner returned no result",
                    "malware_cache_hit": False,
                    "malware_scanned_at": "2026-07-25T12:00:00+00:00",
                },
            ],
        }
    }
    metric_calls: list[tuple[str, object]] = []
    dataframe_calls: list[list[Mapping[str, object]]] = []

    fake_st = SimpleNamespace(
        session_state=session_state,
        error=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        success=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        caption=lambda *args, **kwargs: None,
        tabs=lambda labels: [_Tab() for _ in labels],
        columns=lambda count, **kwargs: [_Column() for _ in range(count)],
        metric=lambda label, value, **kwargs: metric_calls.append((str(label), value)),
        dataframe=lambda rows, **kwargs: dataframe_calls.append(list(rows)),
        expander=lambda *args, **kwargs: _Expander(),
        code=lambda *args, **kwargs: None,
        download_button=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr("ui_home.st", fake_st)

    _render_malware_result_dialog_body()

    assert (t("home.malware_result.metrics.mode_excluded_files"), 1) in metric_calls
    rendered_values = [str(value) for rows in dataframe_calls for row in rows for value in row.values()]
    assert "skip.txt" in rendered_values
    assert "missing.bin" in rendered_values
