from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from services import UploadedFileData


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
    st.markdown(f'<div class="{class_name}">', unsafe_allow_html=True)


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def is_debug() -> bool:
    return bool(st.session_state.get("debug_mode", False))


def handle_ui_exception(user_message: str, exc: Exception) -> None:
    if is_debug():
        st.exception(exc)
    else:
        st.error(user_message)


def build_uploaded_file_batch(uploaded_files: list[Any]) -> list[UploadedFileData]:
    return [
        UploadedFileData(
            name=uploaded_file.name,
            content=bytes(uploaded_file.getbuffer()),
            mime_type=str(getattr(uploaded_file, "type", "") or ""),
        )
        for uploaded_file in uploaded_files
    ]
