from __future__ import annotations

import streamlit as st

SESSION_ANALYSIS_RESULTS = "analysis_results"
SESSION_CONFIRMED_RESULTS = "confirmed_results"
SESSION_EXECUTION_RESULTS = "execution_results"
SESSION_CLEANUP_ACTIONS = "cleanup_actions"
SESSION_REVIEW_SUMMARIES = "review_summaries"
SESSION_FOLDER_SCAN_CURRENT = "folder_scan_current"
SESSION_FOLDER_REPORT_SNAPSHOT = "folder_report_snapshot"
SESSION_FOLDER_LAST_OPERATION_RESULT = "folder_last_operation_result"
SESSION_FOLDER_SCAN_ACTIONS = "folder_scan_actions"
SESSION_FOLDER_SCAN_OPTIONS = "folder_scan_options"
SESSION_FOLDER_RESTORE_RESULT = "folder_restore_result"
SESSION_FOLDER_SCAN_PATH = "folder_scan_path"
SESSION_PROCESSING_OPTIONS = "processing_options"
SESSION_AI_ENABLED = "ai_enabled"
SESSION_DEBUG_MODE = "debug_mode"

SESSION_FOLDER_SCAN = SESSION_FOLDER_SCAN_CURRENT
SESSION_FOLDER_OPERATION_RESULT = SESSION_FOLDER_LAST_OPERATION_RESULT


SESSION_DEFAULTS: dict[str, object] = {
    SESSION_ANALYSIS_RESULTS: [],
    SESSION_CONFIRMED_RESULTS: [],
    SESSION_EXECUTION_RESULTS: [],
    SESSION_CLEANUP_ACTIONS: [],
    "dependency_status": None,
    SESSION_REVIEW_SUMMARIES: {},
    SESSION_FOLDER_SCAN_CURRENT: None,
    SESSION_FOLDER_REPORT_SNAPSHOT: None,
    SESSION_FOLDER_LAST_OPERATION_RESULT: None,
    SESSION_FOLDER_SCAN_ACTIONS: [],
    SESSION_FOLDER_SCAN_OPTIONS: {
        "dry_run": True,
        "stale_days": 364,
        "recursive": True,
        "max_files": 5000,
        "large_file_bytes": 250 * 1024 * 1024,
    },
    SESSION_FOLDER_RESTORE_RESULT: None,
    SESSION_FOLDER_SCAN_PATH: "",
    SESSION_PROCESSING_OPTIONS: {
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
    SESSION_AI_ENABLED: False,
    SESSION_DEBUG_MODE: False,
}


def init_session_state() -> None:
    for key, value in SESSION_DEFAULTS.items():
        st.session_state.setdefault(
            key,
            value.copy() if isinstance(value, dict) else list(value) if isinstance(value, list) else value,
        )


def reset_review_state() -> None:
    st.session_state[SESSION_REVIEW_SUMMARIES] = {}
