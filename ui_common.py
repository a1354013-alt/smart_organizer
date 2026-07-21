from __future__ import annotations

import inspect
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

from i18n import t
from services import UploadedFileData
from ui_state import SESSION_DEBUG_MODE


@dataclass(slots=True)
class UIContext:
    processor: Any
    storage: Any
    project_root: Path
    upload_dir: Path
    repo_root: Path
    db_path: Path
    max_upload_bytes: int
    max_upload_batch_bytes: int = 0
    pandas: Any = None
    plt: Any = None


def safe_display_text(value: object, *, max_chars: int = 2000) -> str:
    """Escape user-controlled text before passing it through markdown-like UI paths."""
    text = "" if value is None else str(value)
    text = text.replace("\x00", "\uFFFD")
    if len(text) > max_chars:
        text = f"{text[:max_chars]}..."
    return escape(text, quote=False)


_CSS_CLASS_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def safe_css_class_name(value: str) -> str:
    if not _CSS_CLASS_NAME_RE.fullmatch(value):
        raise ValueError(f"Unsafe CSS class name: {value!r}")
    return value


def render_safe_html_text(class_name: str, value: object, *, max_chars: int = 2000) -> None:
    st.markdown(
        f'<div class="{safe_css_class_name(class_name)}">{safe_display_text(value, max_chars=max_chars)}</div>',
        unsafe_allow_html=True,
    )


def format_timestamp_for_display(value: object) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    text = str(value).strip()
    if not text:
        return "-"
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def format_bytes(num_bytes: int) -> str:
    value = float(max(0, int(num_bytes)))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024.0 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{value:.1f} GB"


def inject_global_css() -> None:
    st.markdown(
        """
        <style>
          :root {
            --so-bg: #f6f9fc;
            --so-surface: rgba(255, 255, 255, 0.96);
            --so-surface-muted: rgba(248, 250, 252, 0.98);
            --so-border: rgba(15, 23, 42, 0.08);
            --so-text: #0f172a;
            --so-muted: rgba(15, 23, 42, 0.65);
            --so-accent: #ff4b6e;
            --so-accent-2: #db3056;
            --so-warning: #fef3c7;
            --so-danger: #dc2626;
            --so-success: #15803d;
            --so-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
            --so-radius: 18px;
            --so-primary-border: rgba(255, 75, 110, 0.16);
            --so-secondary-border: rgba(15, 118, 110, 0.16);
            --so-header-height: 3.25rem;
          }

          html,
          body {
            min-height: 100vh;
            min-height: 100dvh;
            overflow-x: hidden;
            overflow-y: visible;
          }

          body {
            color: var(--so-text);
          }

          .stApp,
          [data-testid="stAppViewContainer"],
          [data-testid="stAppViewContainer"] > .main {
            min-height: 100vh;
            min-height: 100dvh;
          }

          [data-testid="stAppViewContainer"],
          [data-testid="stAppViewContainer"] > .main {
            overflow: visible;
          }

          .stApp {
            background: radial-gradient(900px 460px at 10% -10%, rgba(15, 118, 110, 0.10), transparent 58%),
                        radial-gradient(780px 420px at 95% 0%, rgba(255, 75, 110, 0.10), transparent 52%),
                        var(--so-bg);
            color: var(--so-text);
            overflow: visible;
          }

          .block-container {
            min-height: calc(100vh - var(--so-header-height));
            min-height: calc(100dvh - var(--so-header-height));
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            overflow-x: hidden;
            padding-top: 1rem;
            padding-bottom: 1rem;
            padding-left: 1rem;
            padding-right: 1rem;
          }

          section[data-testid="stSidebar"] {
            min-height: 100vh;
            min-height: 100dvh;
            overflow: hidden;
            background: rgba(255, 255, 255, 0.86);
            border-right: 1px solid rgba(15, 23, 42, 0.06);
          }

          section[data-testid="stSidebar"] > div:first-child {
            min-height: 100vh;
            min-height: 100dvh;
            overflow-y: auto;
          }

          .st-key-home_shell {
            display: flex;
            flex: 1 1 auto;
            flex-direction: column;
            min-height: 100%;
          }

          .st-key-home_viewport {
            flex: 1 1 auto;
            min-height: 0;
          }

          .st-key-home_footer {
            margin-top: auto;
            padding-top: 0.75rem;
          }

          section[data-testid="stSidebar"],
          section[data-testid="stSidebar"] * {
            color: #0f172a;
          }

          section[data-testid="stSidebar"] label,
          section[data-testid="stSidebar"] p,
          section[data-testid="stSidebar"] span {
            color: #0f172a;
          }

          .stMarkdown,
          .stCaption,
          label,
          p,
          span {
            color: inherit;
          }

          section[data-testid="stSidebar"] .stMarkdown,
          section[data-testid="stSidebar"] .stCaption,
          section[data-testid="stSidebar"] label {
            line-height: 1.45;
          }

          [data-testid="stVerticalBlock"] > [data-testid="stVerticalBlockBorderWrapper"] {
            background: transparent;
          }

          .so-card,
          .so-dialog-body {
            background: var(--so-surface);
            border: 1px solid var(--so-border);
            border-radius: var(--so-radius);
            box-shadow: var(--so-shadow);
            padding: 16px 18px;
          }

          .so-card {
            margin: 0 0 12px 0;
          }

          .so-card-primary {
            background: linear-gradient(135deg, rgba(255, 241, 242, 0.98), rgba(248, 250, 252, 0.95));
            border-color: var(--so-primary-border);
          }

          .so-card-secondary {
            background: linear-gradient(135deg, rgba(240, 253, 250, 0.98), rgba(248, 250, 252, 0.95));
            border-color: var(--so-secondary-border);
          }

          .so-card-compact {
            padding: 14px 16px;
          }

          .so-card-scroll {
            overflow: hidden;
          }

          .so-stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(128px, 1fr));
            gap: 10px;
            margin-top: 8px;
            margin-bottom: 10px;
          }

          .so-stat-card {
            background: var(--so-surface-muted);
            border: 1px solid var(--so-border);
            border-radius: 14px;
            padding: 12px 14px;
          }

          .so-toolbar {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            align-items: center;
          }

          .so-toolbar-status {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            color: var(--so-muted);
            font-size: 13px;
          }

          .so-header {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-start;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 10px;
          }

          .so-header-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            justify-content: flex-end;
          }

          .hero-row {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 16px;
          }

          .hero-title {
            font-size: 28px;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin: 0;
          }

          .version-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 4px 10px;
            border-radius: 999px;
            background: rgba(37, 99, 235, 0.08);
            border: 1px solid rgba(37, 99, 235, 0.18);
            color: rgba(15, 23, 42, 0.85);
            font-weight: 700;
            font-size: 12px;
            white-space: nowrap;
          }

          .hero-subtitle,
          .so-dialog-body p {
            margin: 6px 0 0 0;
            color: var(--so-muted);
            font-size: 14px;
            line-height: 1.55;
            max-width: 820px;
          }

          .feature-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 10px;
          }

          .feature-chip {
            display: inline-flex;
            align-items: center;
            padding: 5px 10px;
            border-radius: 999px;
            background: rgba(15, 118, 110, 0.08);
            border: 1px solid rgba(15, 118, 110, 0.16);
            color: rgba(15, 23, 42, 0.85);
            font-weight: 650;
            font-size: 12.5px;
            white-space: nowrap;
          }

          .card-title {
            font-size: 16px;
            font-weight: 800;
            margin: 0 0 6px 0;
          }

          .card-muted {
            color: var(--so-muted);
            font-size: 13px;
            line-height: 1.55;
            margin: 0;
          }

          .status-metric {
            font-weight: 900;
            font-size: 22px;
            margin: 0;
          }

          .status-label {
            color: var(--so-muted);
            font-size: 12.5px;
            margin-top: 4px;
          }

          .so-table-summary {
            color: var(--so-muted);
            font-size: 13px;
            margin-bottom: 8px;
          }

          .so-inline-code {
            font-family: "Consolas", "SFMono-Regular", monospace;
            font-size: 12px;
          }

          [data-testid="stDataFrame"],
          [data-testid="stDataEditor"] {
            max-width: 100%;
          }

          [data-testid="stDataFrame"] div[role="grid"],
          [data-testid="stDataEditor"] div[role="grid"] {
            min-width: 0;
          }

          .stButton > button,
          .stDownloadButton > button {
            border-radius: 12px;
          }

          .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, var(--so-accent), var(--so-accent-2));
            border: 1px solid rgba(255, 75, 110, 0.24);
          }

          @media (max-width: 900px) {
            html,
            body,
            .stApp,
            [data-testid="stAppViewContainer"] {
              min-height: 0;
              overflow: visible;
            }

            [data-testid="stAppViewContainer"] > .main {
              min-height: 0;
            }

            .block-container {
              min-height: 0;
              overflow: visible;
              padding-left: 0.75rem;
              padding-right: 0.75rem;
            }

            section[data-testid="stSidebar"] {
              min-height: 0;
              overflow: visible;
            }

            section[data-testid="stSidebar"] > div:first-child {
              min-height: 0;
              overflow-y: visible;
            }

            .st-key-home_shell,
            .st-key-home_viewport {
              display: block;
              min-height: 0;
            }

            .st-key-home_footer {
              margin-top: 0;
            }

            .so-header,
            .hero-row {
              flex-direction: column;
            }

            .so-header-actions {
              justify-content: flex-start;
            }
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def card_open(class_name: str) -> None:
    """Deprecated: do not wrap Streamlit widgets across markdown blocks with this helper."""
    st.markdown(f'<div class="{safe_css_class_name(class_name)}">', unsafe_allow_html=True)


def card_close() -> None:
    """Deprecated: close the matching HTML-only card opened by ``card_open``."""
    st.markdown("</div>", unsafe_allow_html=True)


def open_dialog_state(key: str) -> None:
    st.session_state[key] = True


def close_dialog_state(key: str) -> None:
    st.session_state[key] = False


_dialog_rendered_this_run = False


def reset_dialog_render_cycle() -> None:
    global _dialog_rendered_this_run
    _dialog_rendered_this_run = False


def render_dialog(
    *,
    key: str,
    title: str,
    render_body: Callable[[], None],
    width: str = "small",
    dismissible: bool = True,
    on_dismiss: Callable[[], None] | None = None,
    dismiss_state_keys: tuple[str, ...] = (),
) -> None:
    global _dialog_rendered_this_run
    if not st.session_state.get(key):
        return
    if _dialog_rendered_this_run:
        return

    def _handle_dismiss() -> None:
        close_dialog_state(key)
        for dismiss_key in dismiss_state_keys:
            st.session_state[dismiss_key] = None
        if on_dismiss is not None:
            on_dismiss()

    if hasattr(st, "dialog"):
        dialog_params: dict[str, Any] = {"width": width, "dismissible": dismissible}
        if "on_dismiss" in inspect.signature(st.dialog).parameters:
            dialog_params["on_dismiss"] = _handle_dismiss if dismissible else "ignore"

        @st.dialog(title, **dialog_params)
        def _dialog() -> None:
            with st.container():
                render_body()
            if st.button(t("common.close"), key=f"{key}_close"):
                _handle_dismiss()
                st.rerun()

        _dialog_rendered_this_run = True
        _dialog()
        return

    with st.expander(title, expanded=True):
        render_body()
        if st.button(t("common.close"), key=f"{key}_close_fallback"):
            _handle_dismiss()
            st.rerun()
    _dialog_rendered_this_run = True


def is_debug() -> bool:
    return bool(st.session_state.get(SESSION_DEBUG_MODE, False))


def handle_ui_exception(user_message: str, exc: Exception) -> None:
    if is_debug():
        st.exception(exc)
    else:
        st.error(safe_display_text(user_message))


def build_uploaded_file_batch(uploaded_files: list[Any]) -> list[UploadedFileData]:
    return [
        UploadedFileData(
            name=uploaded_file.name,
            content=bytes(uploaded_file.getbuffer()),
            mime_type=str(getattr(uploaded_file, "type", "") or ""),
        )
        for uploaded_file in uploaded_files
    ]
