from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

import streamlit as st

from folder_models import (
    RISK_LABELS,
    FolderOrganizerError,
    Recommendation,
    ScanPathError,
    human_bytes,
    safe_int,
)
from folder_report import export_folder_report_csv, export_folder_report_markdown
from folder_service import (
    build_report_snapshot,
    get_quarantine_items_safe,
    preview_selected_actions,
    quarantine_selected_files,
    resolve_report_inputs,
    restore_quarantine_selection,
    scan_folder,
)
from i18n import (
    get_current_language,
    get_language_label,
    get_language_options,
    set_current_language,
    t,
)
from malware_scanner import (
    ClamAvStatus,
    get_clamav_status,
    is_candidate_auto_selectable,
    is_malware_blocked_status,
    update_clamav_database,
)
from ui_common import (
    UIContext,
    close_dialog_state,
    format_timestamp_for_display,
    handle_ui_exception,
    is_debug,
    open_dialog_state,
    render_dialog,
    safe_display_text,
)
from ui_labels import recommendation_display_label, risk_display_label
from ui_renderers import render_dependency_status
from ui_state import (
    SESSION_AI_ENABLED,
    SESSION_DEBUG_MODE,
    SESSION_FOLDER_LAST_OPERATION_RESULT,
    SESSION_FOLDER_REPORT_SNAPSHOT,
    SESSION_FOLDER_RESTORE_RESULT,
    SESSION_FOLDER_SCAN_CURRENT,
    SESSION_FOLDER_SCAN_OPTIONS,
    SESSION_FOLDER_SCAN_PATH,
    SESSION_FOLDER_SELECTED_PATHS,
    SESSION_PROCESSING_OPTIONS,
)
from version import APP_NAME, __version__

DEPENDENCY_STATUS_SESSION_KEY = "dependency_status"
MAX_RENDERED_CANDIDATES = 500
HELP_DIALOG_KEY = "home_dialog_help"
SAFETY_DIALOG_KEY = "home_dialog_safety"
WORKFLOW_DIALOG_KEY = "home_dialog_workflow"
WARNINGS_DIALOG_KEY = "home_dialog_warnings"
REPORT_DIALOG_KEY = "home_dialog_report"
STATS_DIALOG_KEY = "home_dialog_stats"
PATHS_DIALOG_KEY = "home_dialog_paths"
CLAMAV_STATUS_SESSION_KEY = "clamav_status"
CLAMAV_UPDATE_RESULT_SESSION_KEY = "clamav_update_result"
_REASON_LABEL_KEYS = {
    "long_unused": "home.candidates.reason_long_unused",
    "large_file": "home.candidates.reason_large_file",
    "duplicate_candidate": "home.candidates.reason_duplicate_candidate",
    "temp_cache_log": "home.candidates.reason_temp_cache_log",
    "low_confidence": "home.candidates.reason_low_confidence",
}
_DUPLICATE_TYPE_LABEL_KEYS = {
    "same_content_duplicate": "home.candidates.duplicate_type.same_content_duplicate",
    "same_name_candidate": "home.candidates.duplicate_type.same_name_candidate",
    "similar_name_candidate": "home.candidates.duplicate_type.similar_name_candidate",
}
_MALWARE_SCAN_LABEL_KEYS = {
    "clean": "malware.scan_clean",
    "infected": "malware.scan_infected",
    "suspicious": "malware.scan_suspicious",
    "not_scanned": "malware.scan_not_scanned",
    "scanner_unavailable": "malware.scan_scanner_unavailable",
    "database_missing": "malware.scan_database_missing",
    "database_outdated": "malware.scan_database_outdated",
    "error": "malware.scan_error",
    "timeout": "malware.scan_timeout",
}
_CLAMAV_STATUS_LABEL_KEYS = {
    "available": "malware.status_available",
    "clamscan_missing": "malware.status_clamscan_missing",
    "freshclam_missing": "malware.status_freshclam_missing",
    "database_missing": "malware.status_database_missing",
    "database_outdated": "malware.status_database_outdated",
    "unknown": "malware.status_unknown",
}


def _coerce_message_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _localized_reason_list(item: dict[str, object]) -> list[str]:
    codes = [str(code) for code in cast(list[object], item.get("reason_codes") or []) if str(code)]
    if codes:
        return [t(_REASON_LABEL_KEYS.get(code, ""), lang=get_current_language()) if code in _REASON_LABEL_KEYS else code for code in codes]
    reasons = [str(reason) for reason in cast(list[object], item.get("candidate_reasons") or []) if str(reason)]
    return reasons or [t("home.candidates.reason_selected_manually")]


def _duplicate_type_label(value: object) -> str:
    duplicate_type = str(value or "").strip()
    label_key = _DUPLICATE_TYPE_LABEL_KEYS.get(duplicate_type)
    if label_key:
        return t(label_key)
    return duplicate_type or t("home.candidates.duplicate_type.none")


def _candidate_reason_text(item: dict[str, object]) -> str:
    return "; ".join(_localized_reason_list(item))


def _candidate_duplicate_reason_text(item: dict[str, object]) -> str:
    duplicate_reason = str(item.get("duplicate_reason") or "").strip()
    return duplicate_reason or t("home.candidates.duplicate_reason.none")


def _malware_scan_label(value: object) -> str:
    status = str(value or "not_scanned").strip() or "not_scanned"
    label_key = _MALWARE_SCAN_LABEL_KEYS.get(status)
    return t(label_key) if label_key else status


def _blocked_candidate_warning(item: dict[str, object], *, enable_malware_scan: bool = False) -> str | None:
    status = str(item.get("malware_status") or "")
    if not is_malware_blocked_status(status, enable_malware_scan=enable_malware_scan):
        return None
    if status == "infected":
        return t("malware.infected_warning")
    return t("malware.blocked_warning", status=_malware_scan_label(status))


def _serialize_clamav_status(status: ClamAvStatus) -> dict[str, object]:
    return asdict(status)


def _clamav_status_from_session() -> dict[str, object] | None:
    value = st.session_state.get(CLAMAV_STATUS_SESSION_KEY)
    return cast(dict[str, object], value) if isinstance(value, dict) else None


def _render_clamav_status_box(status: dict[str, object]) -> None:
    availability = str(status.get("availability") or "unknown")
    label_key = _CLAMAV_STATUS_LABEL_KEYS.get(availability, "malware.status_unknown")
    summary = t(label_key)
    message = str(status.get("message") or "").strip()
    details = [summary]
    if message and message != summary:
        details.append(message)
    version = str(status.get("database_version") or "").strip()
    if version:
        details.append(t("malware.database_version", version=version))
    database_date = str(status.get("database_date") or "").strip()
    if database_date:
        details.append(t("malware.database_date", date=database_date))
    age_days = status.get("database_age_days")
    if isinstance(age_days, int):
        details.append(t("malware.database_age_days", days=age_days))
    clamscan_path = str(status.get("clamscan_path") or "").strip() or "-"
    freshclam_path = str(status.get("freshclam_path") or "").strip() or "-"
    database_dir = str(status.get("database_dir") or "").strip() or "-"
    details.append(t("malware.clamscan_path", path=clamscan_path))
    details.append(t("malware.freshclam_path", path=freshclam_path))
    details.append(t("malware.database_dir", path=database_dir))
    renderer = st.success if availability == "available" else st.warning
    renderer("\n".join(f"- {line}" for line in details))


def _candidate_row(item: dict[str, object]) -> dict[str, object]:
    return {
        "select": False,
        "name": item.get("name"),
        "recommendation": recommendation_display_label(item.get("recommendation")),
        "risk_level": risk_display_label(item.get("risk_level")),
        "malware_status": _malware_scan_label(item.get("malware_status")),
        "malware_scanner": item.get("malware_scanner") or "-",
        "malware_threat_name": item.get("malware_threat_name") or "-",
        "duplicate_type": _duplicate_type_label(item.get("duplicate_type")),
        "duplicate_reason": _candidate_duplicate_reason_text(item),
        "reasons": _candidate_reason_text(item),
        "size": human_bytes(safe_int(item.get("size_bytes"))),
        "last_modified": format_timestamp_for_display(item.get("mtime")),
        "path": item.get("path"),
    }


def summarize_recommendations(
    records: list[dict[str, object]],
    candidates: list[dict[str, object]],
) -> dict[str, int]:
    return {
        Recommendation.SAFE_TO_REVIEW.value: sum(
            1 for item in candidates if item.get("recommendation") == Recommendation.SAFE_TO_REVIEW.value
        ),
        Recommendation.NEEDS_MANUAL_CHECK.value: sum(
            1 for item in candidates if item.get("recommendation") == Recommendation.NEEDS_MANUAL_CHECK.value
        ),
        Recommendation.DO_NOT_TOUCH.value: sum(
            1 for item in records if item.get("recommendation") == Recommendation.DO_NOT_TOUCH.value
        ),
    }


def get_cached_dependency_status(session_state: Any) -> dict[str, Any] | None:
    status = session_state.get(DEPENDENCY_STATUS_SESSION_KEY)
    return dict(status) if isinstance(status, dict) else None


def cache_dependency_status(session_state: Any, status: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(status)
    session_state[DEPENDENCY_STATUS_SESSION_KEY] = normalized
    return normalized


def refresh_dependency_status(context: UIContext) -> dict[str, Any]:
    try:
        status = context.processor.get_dependency_status(refresh=True)
    except TypeError:
        status = context.processor.get_dependency_status()
    return cache_dependency_status(st.session_state, status)


def limit_candidate_rows(
    candidates: list[dict[str, object]],
    *,
    limit: int = MAX_RENDERED_CANDIDATES,
) -> tuple[list[dict[str, object]], int]:
    normalized_limit = max(1, int(limit))
    visible = list(candidates[:normalized_limit])
    hidden = max(0, len(candidates) - len(visible))
    return visible, hidden


def merge_visible_selection(
    current_selected_paths: set[str],
    visible_rows: list[dict[str, object]],
    edited_rows: list[dict[str, object]],
) -> set[str]:
    visible_paths = {
        str(row.get("path"))
        for row in visible_rows
        if str(row.get("path") or "").strip()
    }
    merged = {path for path in current_selected_paths if path not in visible_paths}
    for row in edited_rows:
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        if bool(row.get("select")):
            merged.add(path)
    return merged


def render_sidebar(context: UIContext) -> None:
    st.sidebar.header(t("sidebar.title"))
    language_options = get_language_options()
    current_language = get_current_language(st.session_state)
    selected_language = st.sidebar.selectbox(
        t("sidebar.language_label"),
        options=language_options,
        index=language_options.index(current_language),
        format_func=get_language_label,
        key="sidebar_ui_language",
    )
    set_current_language(selected_language, st.session_state)

    with st.sidebar.expander(t("sidebar.scan_settings_title"), expanded=True):
        stale_days = st.slider(t("sidebar.stale_days"), 7, 3650, 365, step=7)
        large_file_mb = st.slider(t("sidebar.large_file_mb"), 10, 2048, 250, step=10)
        recursive = st.checkbox(t("sidebar.scan_subfolders"), value=True, key="folder_recursive")
        max_files = st.number_input(t("sidebar.max_files"), min_value=100, max_value=200000, value=5000, step=500)
        enable_malware_scan = st.checkbox(
            t("malware.enable_scan"),
            value=bool((st.session_state.get(SESSION_FOLDER_SCAN_OPTIONS) or {}).get("enable_malware_scan", False)),
            key="folder_enable_malware_scan",
        )
        malware_scan_timeout_seconds = st.number_input(
            t("malware.timeout_seconds"),
            min_value=5,
            max_value=300,
            value=int((st.session_state.get(SESSION_FOLDER_SCAN_OPTIONS) or {}).get("malware_scan_timeout_seconds", 30)),
            step=5,
            key="folder_malware_timeout_seconds",
        )
        malware_database_max_age_days = st.number_input(
            t("malware.database_max_age_days"),
            min_value=1,
            max_value=30,
            value=int((st.session_state.get(SESSION_FOLDER_SCAN_OPTIONS) or {}).get("malware_database_max_age_days", 7)),
            step=1,
            key="folder_malware_database_max_age_days",
        )
        st.session_state[SESSION_FOLDER_SCAN_OPTIONS] = {
            "stale_days": int(stale_days),
            "large_file_bytes": int(large_file_mb) * 1024 * 1024,
            "recursive": bool(recursive),
            "max_files": int(max_files),
            "enable_malware_scan": bool(enable_malware_scan),
            "malware_scan_timeout_seconds": int(malware_scan_timeout_seconds),
            "malware_database_max_age_days": int(malware_database_max_age_days),
        }
        malware_status_cols = st.columns(2, gap="small")
        with malware_status_cols[0]:
            if st.button(t("malware.check_status"), key="check_clamav_status_button", use_container_width=True):
                st.session_state[CLAMAV_STATUS_SESSION_KEY] = _serialize_clamav_status(
                    get_clamav_status(int(malware_database_max_age_days))
                )
        with malware_status_cols[1]:
            if st.button(t("malware.update_database"), key="update_clamav_database_button", use_container_width=True):
                ok, message = update_clamav_database()
                st.session_state[CLAMAV_UPDATE_RESULT_SESSION_KEY] = {"ok": ok, "message": message}
                st.session_state[CLAMAV_STATUS_SESSION_KEY] = _serialize_clamav_status(
                    get_clamav_status(int(malware_database_max_age_days))
                )

        clamav_status = _clamav_status_from_session()
        if clamav_status is not None:
            _render_clamav_status_box(clamav_status)
        update_result = st.session_state.get(CLAMAV_UPDATE_RESULT_SESSION_KEY)
        if isinstance(update_result, dict):
            message = str(update_result.get("message") or "").strip()
            if message:
                if bool(update_result.get("ok")):
                    st.success(message)
                else:
                    st.warning(message)

    with st.sidebar.expander(t("sidebar.advanced_settings_title"), expanded=False):
        debug_mode = st.checkbox(t("sidebar.debug_mode"), value=False, key="debug_mode_checkbox")
        st.session_state[SESSION_DEBUG_MODE] = bool(debug_mode)
        if is_debug() and st.session_state.get("current_processing_file"):
            st.caption(
                t(
                    "sidebar.current_processing_file",
                    name=safe_display_text(st.session_state.current_processing_file),
                )
            )

        ai_enabled = st.toggle(t("sidebar.enable_ai_summary"), value=False, key="ai_enabled_toggle")
        enable_pdf_preview = st.checkbox(t("sidebar.enable_pdf_preview"), value=False, key="enable_pdf_preview")
        enable_ocr = st.checkbox(t("sidebar.enable_ocr"), value=False, key="enable_ocr")
        max_heavy_mb = st.slider(t("sidebar.heavy_file_mb"), 1, 200, 15, key="max_heavy_mb")
        pdf_text_max_pages = st.slider(t("sidebar.pdf_text_pages"), 1, 50, 3, key="pdf_text_max_pages")
        pdf_ocr_max_pages = st.slider(
            t("sidebar.pdf_ocr_pages"),
            1,
            5,
            max(1, min(5, int(getattr(context.processor, "pdf_ocr_max_pages", 3)))),
            key="pdf_ocr_max_pages",
        )
        batch_upload_bytes = int(getattr(context, "max_upload_batch_bytes", context.max_upload_bytes))
        batch_limit_mb = int(max(batch_upload_bytes, context.max_upload_bytes) / (1024 * 1024))
        st.caption(
            t(
                "sidebar.upload_limits",
                file_size=f"{int(context.max_upload_bytes / (1024 * 1024))} MB",
                batch_size=f"{batch_limit_mb} MB",
            )
        )

        st.session_state[SESSION_AI_ENABLED] = bool(ai_enabled)
        st.session_state[SESSION_PROCESSING_OPTIONS] = {
            "enable_pdf_preview": bool(enable_pdf_preview),
            "enable_ocr": bool(enable_ocr),
            "max_heavy_bytes": int(max_heavy_mb) * 1024 * 1024,
            "pdf_text_max_pages": int(pdf_text_max_pages),
            "pdf_ocr_max_pages": int(pdf_ocr_max_pages),
            "pdf_preview_max_pages": int(getattr(context.processor, "pdf_preview_max_pages", 1)),
            "pdf_text_timeout_seconds": 10,
            "pdf_preview_timeout_seconds": 10,
            "ocr_timeout_seconds": 15,
            "video_metadata_timeout_seconds": 10,
            "video_thumbnail_timeout_seconds": 10,
        }

        dependency_status = get_cached_dependency_status(st.session_state)
        if is_debug():
            st.caption(t("sidebar.processing_options"))
            st.json(st.session_state.get(SESSION_PROCESSING_OPTIONS) or {})

        with st.expander(t("sidebar.dependency_check_title"), expanded=False):
            if st.button(t("sidebar.check_dependencies"), key="check_dependencies_button"):
                dependency_status = refresh_dependency_status(context)
                st.success(t("sidebar.dependency_check_success"))
            elif dependency_status is None:
                st.caption(t("sidebar.dependency_check_hint"))

            if dependency_status is not None:
                render_dependency_status(dependency_status)

    with st.sidebar.expander(t("sidebar.development_info_title"), expanded=False):
        st.markdown(
            f"- {t('sidebar.workspace.project_root')}: `{context.project_root}`\n"
            f"- {t('sidebar.workspace.uploads')}: `{context.upload_dir}`\n"
            f"- {t('sidebar.workspace.repo')}: `{context.repo_root}`\n"
            f"- {t('sidebar.workspace.database')}: `{context.db_path}`"
        )


def _render_candidate_editor(
    context: UIContext,
    candidates: list[dict[str, object]],
    *,
    enable_malware_scan: bool,
) -> list[str]:
    if not candidates:
        st.info(t("home.candidates.empty"))
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = []
        return []

    st.caption(
        t(
            "home.candidates.risk_labels",
            labels=" | ".join(recommendation_display_label(label) for label in RISK_LABELS),
        )
    )
    visible_candidates, hidden_count = limit_candidate_rows(candidates)
    rows = [_candidate_row(item) for item in visible_candidates]
    visible_paths = {str(row.get("path")) for row in rows}
    candidate_paths = [str(item.get("path")) for item in candidates if str(item.get("path") or "").strip()]
    candidate_by_path = {str(item.get("path")): item for item in candidates if str(item.get("path") or "").strip()}
    selected_paths = [str(path) for path in cast(list[object], st.session_state.get(SESSION_FOLDER_SELECTED_PATHS, []))]

    action_columns = st.columns(4, gap="small")
    with action_columns[0]:
        if st.button(t("home.candidates.select_all_preview"), key="select_all_candidates_for_preview", use_container_width=True):
            st.session_state[SESSION_FOLDER_SELECTED_PATHS] = [
                str(item.get("path"))
                for item in candidates
                if is_candidate_auto_selectable(item, enable_malware_scan=enable_malware_scan)
            ]
            selected_paths = list(st.session_state[SESSION_FOLDER_SELECTED_PATHS])
    with action_columns[1]:
        if st.button(t("home.candidates.select_safe_review"), key="select_safe_review_candidates", use_container_width=True):
            st.session_state[SESSION_FOLDER_SELECTED_PATHS] = [
                str(item.get("path"))
                for item in candidates
                if item.get("risk_level") == "safe_to_review"
                and is_candidate_auto_selectable(item, enable_malware_scan=enable_malware_scan)
            ]
            selected_paths = list(st.session_state[SESSION_FOLDER_SELECTED_PATHS])
    with action_columns[2]:
        if st.button(t("home.candidates.clear_selection"), key="clear_candidate_selection", use_container_width=True):
            st.session_state[SESSION_FOLDER_SELECTED_PATHS] = []
            selected_paths = []
    with action_columns[3]:
        if st.button(
            t("home.candidates.path_details_button"),
            key="open_candidate_paths_dialog",
            use_container_width=True,
            disabled=not selected_paths,
        ):
            open_dialog_state(PATHS_DIALOG_KEY)

    st.markdown(
        f"""
        <div class="so-table-summary">
          {safe_display_text(t("home.candidates.table_summary", total=len(candidates), shown=len(visible_candidates), hidden=hidden_count, selected=len(selected_paths)))}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if hidden_count:
        st.caption(
            t(
                "home.candidates.limit_warning",
                shown=len(visible_candidates),
                total=len(candidates),
            )
        )

    if context.pandas is not None:
        df = context.pandas.DataFrame(rows)
        if selected_paths:
            df["select"] = df["path"].isin(selected_paths)
        edited = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            height=380,
            column_config={
                "select": st.column_config.CheckboxColumn(t("home.candidates.table.select"), width="small"),
                "name": st.column_config.TextColumn(t("home.candidates.table.name"), width="medium"),
                "recommendation": st.column_config.TextColumn(t("home.candidates.table.recommendation"), width="small"),
                "risk_level": st.column_config.TextColumn(t("home.candidates.table.risk_level"), width="small"),
                "malware_status": st.column_config.TextColumn(t("home.candidates.table.malware_status"), width="small"),
                "malware_scanner": st.column_config.TextColumn(t("home.candidates.table.malware_scanner"), width="small"),
                "malware_threat_name": st.column_config.TextColumn(t("home.candidates.table.malware_threat_name"), width="medium"),
                "duplicate_type": st.column_config.TextColumn(t("home.candidates.table.duplicate_type"), width="medium"),
                "duplicate_reason": st.column_config.TextColumn(
                    t("home.candidates.table.duplicate_reason"), width="medium"
                ),
                "reasons": st.column_config.TextColumn(t("home.candidates.table.reasons"), width="medium"),
                "size": st.column_config.TextColumn(t("home.candidates.table.size"), width="small"),
                "last_modified": st.column_config.TextColumn(t("home.candidates.table.last_modified"), width="medium"),
                "path": None,
            },
            key="folder_candidate_editor",
        )
        edited_rows = cast(list[dict[str, object]], edited.to_dict("records"))
        merged_selected = merge_visible_selection(set(selected_paths), rows, edited_rows)
        selected_paths = [
            path
            for path in candidate_paths
            if path in merged_selected
            and not is_malware_blocked_status(
                candidate_by_path.get(path, {}).get("malware_status"),
                enable_malware_scan=enable_malware_scan,
            )
        ]
        hidden_selected_count = sum(1 for path in selected_paths if path not in visible_paths)
        if hidden_selected_count:
            st.caption(
                t(
                    "home.candidates.hidden_selection_summary",
                    selected=hidden_selected_count,
                    hidden=hidden_count,
                )
            )
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = selected_paths
        return selected_paths

    selected_visible = st.multiselect(
        t("home.candidates.table.select"),
        [str(row["path"]) for row in rows],
        default=[path for path in selected_paths if path in visible_paths],
    )
    table_rows = [{key: value for key, value in row.items() if key != "path"} for row in rows]
    st.dataframe(table_rows, use_container_width=True, height=380)
    fallback_rows = [dict(row, select=str(row["path"]) in selected_visible) for row in rows]
    merged_selected = merge_visible_selection(set(selected_paths), rows, fallback_rows)
    selected = [
        path
        for path in candidate_paths
        if path in merged_selected
        and not is_malware_blocked_status(
            candidate_by_path.get(path, {}).get("malware_status"),
            enable_malware_scan=enable_malware_scan,
        )
    ]
    hidden_selected_count = sum(1 for path in selected if path not in visible_paths)
    if hidden_selected_count:
        st.caption(
            t(
                "home.candidates.hidden_selection_summary",
                selected=hidden_selected_count,
                hidden=hidden_count,
            )
        )
    st.session_state[SESSION_FOLDER_SELECTED_PATHS] = selected
    return selected


def _render_operation_results(operation_result: dict[str, object] | None) -> None:
    if not operation_result:
        return
    summary_obj = operation_result.get("summary")
    summary = cast(dict[str, object], summary_obj) if isinstance(summary_obj, dict) else {}
    st.write(
        f"- {t('home.operation_results.selected', count=summary.get('selected', 0))}\n"
        f"- {t('home.operation_results.success', count=summary.get('success', 0))}\n"
        f"- {t('home.operation_results.failed', count=summary.get('failed', 0))}\n"
        f"- {t('home.operation_results.skipped', count=summary.get('skipped', 0))}"
    )
    st.dataframe(operation_result.get("results") or [], use_container_width=True, height=220)


def _render_process_steps() -> None:
    for column, key in zip(st.columns(4, gap="medium"), ("step1", "step2", "step3", "step4"), strict=False):
        with column, st.container(border=True):
            st.markdown(
                f"""
                <div class="card-title">{safe_display_text(t(f"home.process.{key}_title"))}</div>
                <div class="card-muted">{safe_display_text(t(f"home.process.{key}_desc"))}</div>
                """,
                unsafe_allow_html=True,
            )


def _render_home_header() -> None:
    st.markdown(
        f"""
        <div class="so-card so-card-compact">
          <div class="so-header">
            <div>
              <div class="hero-title">{safe_display_text(t('home.hero.title'))}</div>
              <div class="hero-subtitle">{safe_display_text(t('home.header.subtitle'))}</div>
            </div>
            <div class="so-header-actions">
              <span class="version-badge">v{safe_display_text(__version__)}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_columns = st.columns([1, 1, 1, 5], gap="small")
    with action_columns[0]:
        if st.button(t("home.dialogs.help_button"), key="open_help_dialog", use_container_width=True):
            open_dialog_state(HELP_DIALOG_KEY)
    with action_columns[1]:
        if st.button(t("home.dialogs.safety_button"), key="open_safety_dialog", use_container_width=True):
            open_dialog_state(SAFETY_DIALOG_KEY)
    with action_columns[2]:
        if st.button(t("home.dialogs.workflow_button"), key="open_workflow_dialog", use_container_width=True):
            open_dialog_state(WORKFLOW_DIALOG_KEY)


def _render_help_dialog_body() -> None:
    st.markdown(
        f"""
        <div class="so-dialog-body">
          <div class="hero-subtitle">{safe_display_text(t('home.hero.subtitle'))}</div>
          <div class="feature-chips">
            <span class="feature-chip">{safe_display_text(t('home.hero.chip_scan'))}</span>
            <span class="feature-chip">{safe_display_text(t('home.hero.chip_preview'))}</span>
            <span class="feature-chip">{safe_display_text(t('home.hero.chip_quarantine'))}</span>
            <span class="feature-chip">{safe_display_text(t('home.hero.chip_report'))}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(f"- {t('home.help.scan')}")
    st.markdown(f"- {t('home.help.preview')}")
    st.markdown(f"- {t('home.help.quarantine')}")
    st.markdown(f"- {t('home.help.restore')}")


def _render_home_dialogs(
    *,
    warning_messages: list[str] | None = None,
    report_payload: str | None = None,
    records: list[dict[str, object]] | None = None,
    candidates: list[dict[str, object]] | None = None,
) -> None:
    render_dialog(
        key=HELP_DIALOG_KEY,
        title=t("home.dialogs.help_title"),
        render_body=_render_help_dialog_body,
    )
    render_dialog(
        key=SAFETY_DIALOG_KEY,
        title=t("home.dialogs.safety_title"),
        render_body=lambda: st.info(t("home.safety_notice")),
    )
    render_dialog(
        key=WORKFLOW_DIALOG_KEY,
        title=t("home.dialogs.workflow_title"),
        render_body=_render_process_steps,
    )
    render_dialog(
        key=WARNINGS_DIALOG_KEY,
        title=t("home.dialogs.warnings_title"),
        render_body=lambda: _render_warning_messages(warning_messages or []),
    )
    render_dialog(
        key=REPORT_DIALOG_KEY,
        title=t("home.dialogs.report_preview_title"),
        render_body=lambda: st.code((report_payload or "")[:4000], language="markdown"),
    )
    render_dialog(
        key=STATS_DIALOG_KEY,
        title=t("home.dialogs.stats_title"),
        render_body=lambda: _render_stats_dialog_body(records or [], candidates or []),
    )
    render_dialog(
        key=PATHS_DIALOG_KEY,
        title=t("home.dialogs.paths_title"),
        render_body=_render_selected_path_details,
    )


def _render_warning_messages(messages: list[str]) -> None:
    if not messages:
        st.info(t("home.dialogs.warnings_empty"))
        return
    for message in messages[:100]:
        st.write(f"- {safe_display_text(message)}")


def _render_selected_path_details() -> None:
    selected_paths = [str(path) for path in cast(list[object], st.session_state.get(SESSION_FOLDER_SELECTED_PATHS, []))]
    if not selected_paths:
        st.info(t("home.dialogs.paths_empty"))
        return
    for path in selected_paths:
        st.code(path, language=None)


def _render_stats_dialog_body(records: list[dict[str, object]], candidates: list[dict[str, object]]) -> None:
    top_largest = sorted(records, key=lambda item: safe_int(item.get("size_bytes")), reverse=True)[:10]
    top_stale = sorted(
        [item for item in records if item.get("is_stale")],
        key=lambda item: safe_int(item.get("days_since_access")),
        reverse=True,
    )[:10]
    recommendation_summary = summarize_recommendations(records, candidates)

    left_col, right_col = st.columns(2, gap="medium")
    with left_col:
        st.markdown(f"**{t('home.dashboard.top_largest')}**")
        if top_largest:
            for item in top_largest:
                st.write(f"- {safe_display_text(item.get('name'))} | {human_bytes(safe_int(item.get('size_bytes')))}")
        else:
            st.info(t("home.dashboard.empty_largest"))
    with right_col:
        st.markdown(f"**{t('home.dashboard.top_stale')}**")
        if top_stale:
            for item in top_stale:
                st.write(
                    f"- {safe_display_text(item.get('name'))} | "
                    f"{t('home.dashboard.days_idle', days=safe_display_text(item.get('days_since_access')))}"
                )
        else:
            st.info(t("home.dashboard.empty_stale"))

    st.markdown(f"**{t('home.recommended_actions.title')}**")
    st.write(
        f"- {recommendation_display_label(Recommendation.SAFE_TO_REVIEW.value)}: {recommendation_summary[Recommendation.SAFE_TO_REVIEW.value]}\n"
        f"- {recommendation_display_label(Recommendation.NEEDS_MANUAL_CHECK.value)}: {recommendation_summary[Recommendation.NEEDS_MANUAL_CHECK.value]}\n"
        f"- {recommendation_display_label(Recommendation.DO_NOT_TOUCH.value)}: {recommendation_summary[Recommendation.DO_NOT_TOUCH.value]}"
    )


def _scan_status_summary(folder_path: str, scan: dict[str, object] | None) -> str:
    if scan:
        stats_obj = scan.get("stats")
        stats = cast(dict[str, object], stats_obj) if isinstance(stats_obj, dict) else {}
        return t(
            "home.scan.status_ready",
            path=str(scan.get("path") or folder_path or "-"),
            scanned=stats.get("scanned_files", 0),
        )
    if folder_path:
        return t("home.scan.status_input_ready", path=folder_path)
    return t("home.scan.status_empty")


def _render_scan_metrics(stats: dict[str, object], candidates: list[dict[str, object]], quarantined_count: int) -> None:
    metrics = [
        (stats.get("scanned_files", 0), t("home.metrics.scanned_files")),
        (len(candidates), t("home.metrics.candidates")),
        (human_bytes(safe_int(stats.get("total_bytes"))), t("home.metrics.total_size")),
        (stats.get("stale_candidates", 0), t("home.metrics.stale_candidates")),
        (stats.get("large_candidates", 0), t("home.metrics.large_candidates")),
        (quarantined_count, t("home.metrics.quarantined")),
    ]
    metric_markup = "".join(
        (
            '<div class="so-stat-card">'
            f'<div class="status-metric">{safe_display_text(value, max_chars=200)}</div>'
            f'<div class="status-label">{safe_display_text(label, max_chars=200)}</div>'
            "</div>"
        )
        for value, label in metrics
    )
    st.markdown(f'<div class="so-stats-grid">{metric_markup}</div>', unsafe_allow_html=True)


def _render_scan_panel(
    context: UIContext,
    *,
    folder_path: str,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    enable_malware_scan: bool,
    malware_scan_timeout_seconds: int,
    malware_database_max_age_days: int,
    scan: dict[str, object] | None,
) -> None:
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="card-title">{safe_display_text(t("home.scan.title"))}</div>
            <div class="card-muted">{safe_display_text(t("home.scan.description"))}</div>
            """,
            unsafe_allow_html=True,
        )
        st.text_input(
            t("home.scan.input_label"),
            value=folder_path,
            placeholder=t("home.scan.input_placeholder"),
            key=SESSION_FOLDER_SCAN_PATH,
        )
        toolbar_columns = st.columns([2, 1], gap="small")
        with toolbar_columns[0]:
            st.caption(_scan_status_summary(folder_path, scan))
        with toolbar_columns[1]:
            if st.button(t("home.scan.button"), type="primary", key="scan_folder_button", use_container_width=True):
                try:
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    def on_progress(scanned: int, cap: int) -> None:
                        progress_bar.progress(min(1.0, scanned / max(1, cap)))
                        status_text.text(t("home.scan.progress", count=scanned))

                    st.session_state[SESSION_FOLDER_SCAN_CURRENT] = scan_folder(
                        folder_path,
                        recursive=recursive,
                        max_files=max_files,
                        stale_days=stale_days,
                        large_file_bytes=large_file_bytes,
                        enable_malware_scan=enable_malware_scan,
                        malware_scan_timeout_seconds=malware_scan_timeout_seconds,
                        malware_database_max_age_days=malware_database_max_age_days,
                        progress_callback=on_progress,
                    )
                    progress_bar.progress(1.0)
                    status_text.text(t("home.scan.complete"))
                    st.session_state[SESSION_FOLDER_REPORT_SNAPSHOT] = build_report_snapshot(
                        cast(dict[str, object], st.session_state.get(SESSION_FOLDER_SCAN_CURRENT) or {})
                    )
                    st.session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] = None
                    st.session_state[SESSION_FOLDER_RESTORE_RESULT] = None
                    st.session_state[SESSION_FOLDER_SELECTED_PATHS] = []
                except ScanPathError as exc:
                    st.error(str(exc))
                except PermissionError:
                    st.error(t("home.scan.permission_denied"))
                except FolderOrganizerError as exc:
                    st.error(str(exc))
                except Exception as exc:
                    handle_ui_exception(t("home.scan.failed"), exc)


def _render_results_panel(
    context: UIContext,
    *,
    scan: dict[str, object],
    records: list[dict[str, object]],
    candidates: list[dict[str, object]],
    current_quarantine_items: list[dict[str, object]],
    warning_messages: list[str],
    report_payload: str,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    enable_malware_scan: bool,
    malware_scan_timeout_seconds: int,
    malware_database_max_age_days: int,
) -> None:
    with st.container(border=True):
        stats_obj = scan.get("stats")
        stats = cast(dict[str, object], stats_obj) if isinstance(stats_obj, dict) else {}
        _render_scan_metrics(stats, candidates, len(current_quarantine_items))

        toolbar_columns = st.columns([1, 1, 1, 3], gap="small")
        with toolbar_columns[0]:
            if st.button(
                t("home.dialogs.warnings_button"),
                key="open_warnings_dialog",
                disabled=not warning_messages,
                use_container_width=True,
            ):
                open_dialog_state(WARNINGS_DIALOG_KEY)
        with toolbar_columns[1]:
            if st.button(t("home.dialogs.report_preview_button"), key="open_report_dialog", use_container_width=True):
                open_dialog_state(REPORT_DIALOG_KEY)
        with toolbar_columns[2]:
            if st.button(t("home.dialogs.stats_button"), key="open_stats_dialog", use_container_width=True):
                open_dialog_state(STATS_DIALOG_KEY)

        restored_summary_obj = cast(
            dict[str, object],
            (st.session_state.get(SESSION_FOLDER_RESTORE_RESULT) or {}).get("summary", {})
            if isinstance(st.session_state.get(SESSION_FOLDER_RESTORE_RESULT), dict)
            else {},
        )
        operation_summary_obj = cast(
            dict[str, object],
            (st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT) or {}).get("summary", {})
            if isinstance(st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT), dict)
            else {},
        )
        st.caption(
            t(
                "home.summary.inline",
                scanned=stats.get("scanned_files", 0),
                candidates=len(candidates),
                size=human_bytes(sum(safe_int(item.get("size_bytes")) for item in candidates)),
                quarantined=operation_summary_obj.get("success", 0),
                restored=restored_summary_obj.get("success", 0),
            )
        )

        st.subheader(t("home.candidates.title"))
        selected_paths = _render_candidate_editor(
            context,
            candidates,
            enable_malware_scan=enable_malware_scan,
        )
        blocked_candidates = [
            item
            for item in candidates
            if is_malware_blocked_status(
                item.get("malware_status"),
                enable_malware_scan=enable_malware_scan,
            )
        ]
        for item in blocked_candidates[:10]:
            threat_name = str(item.get("malware_threat_name") or "").strip()
            suffix = f" ({threat_name})" if threat_name else ""
            warning = _blocked_candidate_warning(item, enable_malware_scan=enable_malware_scan)
            if warning:
                st.warning(f"{item.get('name')}{suffix}: {warning}")
        blocked_selected = [
            str(item.get("name") or item.get("path") or "")
            for item in candidates
            if str(item.get("path") or "") in selected_paths
            and is_malware_blocked_status(
                item.get("malware_status"),
                enable_malware_scan=enable_malware_scan,
            )
        ]
        if blocked_selected:
            st.warning(
                t(
                    "malware.selected_blocked_warning",
                    files=", ".join(blocked_selected[:5]),
                )
            )

        action_columns = st.columns([1, 1, 2], gap="small")
        with action_columns[0]:
            if st.button(t("home.candidates.preview_button"), key="preview_folder_action", disabled=not selected_paths, use_container_width=True):
                st.session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] = preview_selected_actions(scan, selected_paths)
        with action_columns[1]:
            confirm_quarantine = st.checkbox(
                t("home.candidates.confirm_quarantine"),
                value=False,
                key="confirm_quarantine_move",
            )
        with action_columns[2]:
            if st.button(
                t("home.candidates.quarantine_button"),
                key="run_folder_action",
                disabled=(not selected_paths or not confirm_quarantine),
                use_container_width=True,
            ):
                operation_result, refreshed_scan, report_snapshot = quarantine_selected_files(
                    scan,
                    selected_paths,
                    recursive=recursive,
                    max_files=max_files,
                    stale_days=stale_days,
                    large_file_bytes=large_file_bytes,
                    enable_malware_scan=enable_malware_scan,
                    malware_scan_timeout_seconds=malware_scan_timeout_seconds,
                    malware_database_max_age_days=malware_database_max_age_days,
                )
                st.session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] = operation_result
                st.session_state[SESSION_FOLDER_REPORT_SNAPSHOT] = report_snapshot
                st.session_state[SESSION_FOLDER_SCAN_CURRENT] = refreshed_scan
                close_dialog_state(PATHS_DIALOG_KEY)
                st.rerun()

        st.subheader(t("home.operation_results.title"))
        _render_operation_results(st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT))

        export_columns = st.columns(2, gap="small")
        with export_columns[0]:
            st.download_button(
                t("home.report.export_md"),
                report_payload,
                file_name="smart-organizer-report.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with export_columns[1]:
            export_scan, export_operation = resolve_report_inputs(
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_SCAN_CURRENT) or {}),
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_REPORT_SNAPSHOT) or {}),
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT) or {}),
            )
            st.download_button(
                t("home.report.export_csv"),
                export_folder_report_csv(export_scan, export_operation),
                file_name="smart-organizer-report.csv",
                mime="text/csv",
                use_container_width=True,
            )


def _render_quarantine_panel(
    *,
    folder_path: str,
    current_scan: dict[str, object],
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    enable_malware_scan: bool,
    malware_scan_timeout_seconds: int,
    malware_database_max_age_days: int,
) -> None:
    with st.container(border=True):
        st.markdown(
            f"""
            <div class="card-title">{safe_display_text(t("home.quarantine.title"))}</div>
            <div class="card-muted">{safe_display_text(t("home.quarantine.description"))}</div>
            """,
            unsafe_allow_html=True,
        )
        quarantine_items: list[dict[str, object]] = []
        restore_quarantine_warnings: list[str] = []
        if current_scan or folder_path:
            quarantine_items, restore_quarantine_warnings = get_quarantine_items_safe(
                str(current_scan.get("path") or folder_path or "")
            )
        for warning in restore_quarantine_warnings:
            st.warning(safe_display_text(warning))
        if quarantine_items:
            restore_choices = st.multiselect(
                t("home.quarantine.restore_label"),
                options=[item["quarantine_path"] for item in quarantine_items],
                format_func=lambda value: Path(value).name,
                key="quarantine_restore_paths",
            )
            if st.button(
                t("home.quarantine.restore_button"),
                disabled=not restore_choices,
                key="restore_quarantine_button",
                use_container_width=True,
            ):
                restore_result, restored_scan = restore_quarantine_selection(
                    str(current_scan.get("path") or folder_path),
                    [str(value) for value in restore_choices],
                    recursive=recursive,
                    max_files=max_files,
                    stale_days=stale_days,
                    large_file_bytes=large_file_bytes,
                    enable_malware_scan=enable_malware_scan,
                    malware_scan_timeout_seconds=malware_scan_timeout_seconds,
                    malware_database_max_age_days=malware_database_max_age_days,
                )
                st.session_state[SESSION_FOLDER_RESTORE_RESULT] = restore_result
                if restored_scan is not None:
                    st.session_state[SESSION_FOLDER_SCAN_CURRENT] = restored_scan
                st.rerun()
            _render_operation_results(st.session_state.get(SESSION_FOLDER_RESTORE_RESULT))
        else:
            st.info(t("home.quarantine.empty"))


def render_home(context: UIContext) -> None:
    scan_options_obj = st.session_state.get(SESSION_FOLDER_SCAN_OPTIONS)
    scan_options = cast(dict[str, object], scan_options_obj) if isinstance(scan_options_obj, dict) else {}
    stale_days = safe_int(scan_options.get("stale_days", 365))
    recursive = bool(scan_options.get("recursive", True))
    max_files = safe_int(scan_options.get("max_files", 5000))
    large_file_bytes = safe_int(scan_options.get("large_file_bytes", 250 * 1024 * 1024))
    enable_malware_scan = bool(scan_options.get("enable_malware_scan", False))
    malware_scan_timeout_seconds = safe_int(scan_options.get("malware_scan_timeout_seconds", 30))
    malware_database_max_age_days = safe_int(scan_options.get("malware_database_max_age_days", 7))
    folder_path = str(st.session_state.get(SESSION_FOLDER_SCAN_PATH) or "")
    initial_scan = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_SCAN_CURRENT))
    current_scan = cast(dict[str, object], initial_scan or {})
    _render_home_header()

    top_col, action_col = st.columns([2, 1], gap="medium")
    with top_col:
        _render_scan_panel(
            context,
            folder_path=folder_path,
            recursive=recursive,
            max_files=max_files,
            stale_days=stale_days,
            large_file_bytes=large_file_bytes,
            enable_malware_scan=enable_malware_scan,
            malware_scan_timeout_seconds=malware_scan_timeout_seconds,
            malware_database_max_age_days=malware_database_max_age_days,
            scan=initial_scan,
        )
    with action_col:
        _render_quarantine_panel(
            folder_path=folder_path,
            current_scan=current_scan,
            recursive=recursive,
            max_files=max_files,
            stale_days=stale_days,
            large_file_bytes=large_file_bytes,
            enable_malware_scan=enable_malware_scan,
            malware_scan_timeout_seconds=malware_scan_timeout_seconds,
            malware_database_max_age_days=malware_database_max_age_days,
        )

    scan = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_SCAN_CURRENT))
    warning_messages: list[str] = []
    records: list[dict[str, object]] = []
    candidates: list[dict[str, object]] = []
    current_quarantine_items: list[dict[str, object]] = []
    report_payload = ""
    if scan:
        current_quarantine_items, scan_quarantine_warnings = get_quarantine_items_safe(str(scan.get("path") or ""))
        records = [item for item in cast(list[object], scan.get("records") or []) if isinstance(item, dict)]
        candidates = [item for item in records if item.get("candidate_reasons")]
        errors = _coerce_message_list(scan.get("errors"))
        notes = _coerce_message_list(scan.get("notes"))
        if scan_quarantine_warnings:
            errors.extend(scan_quarantine_warnings)
        warning_messages = [*notes, *errors]
        export_scan, export_operation = resolve_report_inputs(
            cast(dict[str, object], st.session_state.get(SESSION_FOLDER_SCAN_CURRENT) or {}),
            cast(dict[str, object], st.session_state.get(SESSION_FOLDER_REPORT_SNAPSHOT) or {}),
            cast(dict[str, object], st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT) or {}),
        )
        report_payload = export_folder_report_markdown(export_scan, export_operation)
        _render_results_panel(
            context,
            scan=scan,
            records=records,
            candidates=candidates,
            current_quarantine_items=current_quarantine_items,
            warning_messages=warning_messages,
            report_payload=report_payload,
            recursive=recursive,
            max_files=max_files,
            stale_days=stale_days,
            large_file_bytes=large_file_bytes,
            enable_malware_scan=enable_malware_scan,
            malware_scan_timeout_seconds=malware_scan_timeout_seconds,
            malware_database_max_age_days=malware_database_max_age_days,
        )
    else:
        st.info(t("home.scan.empty"))

    _render_home_dialogs(
        warning_messages=warning_messages,
        report_payload=report_payload,
        records=records,
        candidates=candidates,
    )

    st.caption(f"{APP_NAME} v{__version__}")
