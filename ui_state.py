from __future__ import annotations

import streamlit as st


SESSION_DEFAULTS: dict[str, object] = {
    "analysis_results": [],
    "confirmed_results": [],
    "execution_results": [],
    "cleanup_actions": [],
    "review_summaries": {},
    "folder_scan": None,
    "folder_scan_actions": [],
    "folder_scan_options": {
        "dry_run": True,
        "stale_days": 364,
        "recursive": True,
        "max_files": 5000,
    },
    "processing_options": {
        "enable_pdf_preview": False,
        "enable_ocr": False,
        "max_heavy_bytes": 15 * 1024 * 1024,
        "pdf_text_max_pages": 3,
        "pdf_ocr_max_pages": 3,
        "pdf_preview_max_pages": 1,
        "pdf_text_timeout_seconds": 10,
        "pdf_preview_timeout_seconds": 10,
        "ocr_timeout_seconds": 15,
        "video_metadata_timeout_seconds": 10,
        "video_thumbnail_timeout_seconds": 10,
    },
    "ai_enabled": False,
    "debug_mode": False,
}


def init_session_state() -> None:
    for key, value in SESSION_DEFAULTS.items():
        st.session_state.setdefault(key, value.copy() if isinstance(value, dict) else list(value) if isinstance(value, list) else value)


def reset_review_state() -> None:
    st.session_state.review_summaries = {}
