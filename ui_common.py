from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import streamlit as st

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
            --so-bg: #f7faf8;
            --so-surface: rgba(255, 255, 255, 0.92);
            --so-border: rgba(15, 23, 42, 0.10);
            --so-text: #0f172a;
            --so-muted: rgba(15, 23, 42, 0.65);
            --so-accent: #10b981;
            --so-accent-2: #3b82f6;
            --so-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
            --so-radius: 20px;
            --so-primary-border: rgba(16, 185, 129, 0.25);
            --so-secondary-border: rgba(59, 130, 246, 0.22);
          }

          .stApp {
            background: radial-gradient(1200px 600px at 20% -10%, rgba(16, 185, 129, 0.10), transparent 60%),
                        radial-gradient(900px 500px at 90% 0%, rgba(59, 130, 246, 0.10), transparent 55%),
                        var(--so-bg);
            color: var(--so-text);
          }

          section[data-testid="stSidebar"] {
            background: rgba(255, 255, 255, 0.70);
            border-right: 1px solid rgba(15, 23, 42, 0.06);
          }

          .hero-card,
          .primary-action-card,
          .secondary-action-card,
          .status-card {
            background: var(--so-surface);
            border: 1px solid var(--so-border);
            border-radius: var(--so-radius);
            box-shadow: var(--so-shadow);
            padding: 18px 18px;
            margin: 6px 0 14px 0;
          }

          .primary-action-card {
            background: linear-gradient(135deg, rgba(236, 253, 245, 0.98), rgba(255, 251, 235, 0.92));
            border-color: var(--so-primary-border);
          }

          .secondary-action-card {
            background: linear-gradient(135deg, rgba(239, 246, 255, 0.98), rgba(248, 250, 252, 0.92));
            border-color: var(--so-secondary-border);
          }

          .hero-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin: 0;
          }

          .version-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 10px;
            border-radius: 999px;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.30);
            color: rgba(15, 23, 42, 0.85);
            font-weight: 700;
            font-size: 13px;
            white-space: nowrap;
          }

          .hero-subtitle {
            margin: 8px 0 0 0;
            color: var(--so-muted);
            font-size: 14px;
            line-height: 1.55;
          }

          .feature-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
          }

          .feature-chip {
            display: inline-flex;
            align-items: center;
            padding: 6px 10px;
            border-radius: 999px;
            background: rgba(2, 132, 199, 0.08);
            border: 1px solid rgba(2, 132, 199, 0.20);
            color: rgba(15, 23, 42, 0.85);
            font-weight: 650;
            font-size: 12.5px;
            white-space: nowrap;
          }

          .card-title {
            font-size: 16px;
            font-weight: 800;
            margin: 0 0 8px 0;
          }

          .card-muted {
            color: var(--so-muted);
            font-size: 13px;
            line-height: 1.55;
            margin: 0 0 8px 0;
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
        </style>
        """,
        unsafe_allow_html=True,
    )


def card_open(class_name: str) -> None:
    st.markdown(f'<div class="{safe_css_class_name(class_name)}">', unsafe_allow_html=True)


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


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
