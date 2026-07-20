from __future__ import annotations

import streamlit as st

from i18n import DEFAULT_LANGUAGE, SESSION_UI_LANGUAGE

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
SESSION_FOLDER_SCAN_OPTIONS_DRAFT = "folder_scan_options_draft"
SESSION_FOLDER_SETTINGS_DIALOG_OPEN = "folder_settings_dialog_open"
SESSION_FOLDER_MALWARE_SCAN_RESULT = "folder_malware_scan_result"
SESSION_FOLDER_MALWARE_DIALOG_OPEN = "folder_malware_dialog_open"
SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID = "folder_malware_auto_open_result_id"
SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID = "folder_malware_dismissed_result_id"
SESSION_FOLDER_ANALYSIS_DIALOG_OPEN = "folder_analysis_dialog_open"
SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID = "folder_analysis_auto_open_result_id"
SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID = "folder_analysis_dismissed_result_id"
SESSION_FOLDER_RESTORE_RESULT = "folder_restore_result"
SESSION_FOLDER_SCAN_PATH = "folder_scan_path"
SESSION_FOLDER_SELECTED_PATHS = "folder_selected_paths"
SESSION_MAIN_TAB_OVERRIDE = "main_tab_override"
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
        "stale_days": 364,
        "recursive": True,
        "max_files": 5000,
        "large_file_bytes": 250 * 1024 * 1024,
        "duplicate_detection": False,
        "enable_malware_scan": False,
        "malware_scan_mode": "standard",
        "malware_scan_policy": "standard",
        "malware_scan_timeout_seconds": 30,
        "malware_database_max_age_days": 7,
        "malware_only_operation": False,
    },
    SESSION_FOLDER_SCAN_OPTIONS_DRAFT: {},
    SESSION_FOLDER_SETTINGS_DIALOG_OPEN: False,
    SESSION_FOLDER_MALWARE_SCAN_RESULT: None,
    SESSION_FOLDER_MALWARE_DIALOG_OPEN: False,
    SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID: None,
    SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID: None,
    SESSION_FOLDER_ANALYSIS_DIALOG_OPEN: False,
    SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID: None,
    SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID: None,
    SESSION_FOLDER_RESTORE_RESULT: None,
    SESSION_FOLDER_SCAN_PATH: "",
    SESSION_FOLDER_SELECTED_PATHS: [],
    SESSION_MAIN_TAB_OVERRIDE: None,
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
    SESSION_UI_LANGUAGE: DEFAULT_LANGUAGE,
}


def init_session_state() -> None:
    for key, value in SESSION_DEFAULTS.items():
        st.session_state.setdefault(
            key,
            value.copy() if isinstance(value, dict) else list(value) if isinstance(value, list) else value,
        )


def reset_review_state() -> None:
    st.session_state[SESSION_REVIEW_SUMMARIES] = {}
