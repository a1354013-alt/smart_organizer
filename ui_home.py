from __future__ import annotations

import csv
import io
import uuid
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
    malware_result_conclusion_key,
    malware_result_severity,
    merge_malware_scan_into_analysis,
    preview_selected_actions,
    quarantine_selected_files,
    resolve_report_inputs,
    restore_quarantine_selection,
    scan_folder,
    scan_folder_malware,
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
from path_utils import canonical_path_key
from ui_common import (
    UIContext,
    close_dialog_state,
    format_timestamp_for_display,
    handle_ui_exception,
    open_dialog_state,
    render_dialog,
    reset_dialog_render_cycle,
    safe_display_text,
)
from ui_labels import recommendation_display_label, risk_display_label
from ui_state import (
    SESSION_AI_ENABLED,
    SESSION_DEBUG_MODE,
    SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID,
    SESSION_FOLDER_ANALYSIS_DIALOG_OPEN,
    SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID,
    SESSION_FOLDER_LAST_OPERATION_RESULT,
    SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID,
    SESSION_FOLDER_MALWARE_DIALOG_OPEN,
    SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID,
    SESSION_FOLDER_MALWARE_SCAN_RESULT,
    SESSION_FOLDER_REPORT_SNAPSHOT,
    SESSION_FOLDER_RESTORE_RESULT,
    SESSION_FOLDER_SCAN_CURRENT,
    SESSION_FOLDER_SCAN_OPTIONS,
    SESSION_FOLDER_SCAN_OPTIONS_DRAFT,
    SESSION_FOLDER_SCAN_PATH,
    SESSION_FOLDER_SELECTED_PATHS,
    SESSION_FOLDER_SETTINGS_DIALOG_OPEN,
    SESSION_MAIN_TAB_OVERRIDE,
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
SETTINGS_DIALOG_KEY = SESSION_FOLDER_SETTINGS_DIALOG_OPEN
MALWARE_RESULT_DIALOG_KEY = SESSION_FOLDER_MALWARE_DIALOG_OPEN
ANALYSIS_RESULT_DIALOG_KEY = SESSION_FOLDER_ANALYSIS_DIALOG_OPEN
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
    "mode_excluded": "home.malware_result.health.mode_excluded",
    "scanner_unavailable": "malware.scan_scanner_unavailable",
    "database_missing": "malware.scan_database_missing",
    "database_outdated": "malware.scan_database_outdated",
    "error": "malware.scan_error",
    "timeout": "malware.scan_timeout",
    "limit_exceeded": "home.malware_result.health.limit_exceeded",
    "incomplete": "home.malware_result.health.other_incomplete",
}
_MALWARE_SCAN_HEALTH_LABEL_KEYS = {
    "ok": "home.malware_result.health.ok",
    "scanner_unavailable": "home.malware_result.health.scanner_unavailable",
    "database_missing": "home.malware_result.health.database_missing",
    "database_outdated": "home.malware_result.health.database_outdated",
    "timeout": "home.malware_result.health.timeout",
    "error": "home.malware_result.health.backend_error",
    "limit_exceeded": "home.malware_result.health.limit_exceeded",
    "incomplete": "home.malware_result.health.other_incomplete",
    "mode_excluded": "home.malware_result.health.mode_excluded",
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


def _malware_scan_health_label(value: object) -> str:
    health = str(value or "incomplete").strip() or "incomplete"
    label_key = _MALWARE_SCAN_HEALTH_LABEL_KEYS.get(health)
    return t(label_key) if label_key else health


def _malware_incomplete_group(health: object, message: object) -> str:
    normalized = str(health or "incomplete").strip() or "incomplete"
    message_text = str(message or "").strip().lower()
    if normalized == "mode_excluded":
        return "mode_excluded"
    if normalized in {
        "scanner_unavailable",
        "database_missing",
        "database_outdated",
        "timeout",
        "limit_exceeded",
    }:
        return normalized
    if normalized == "error":
        if "permission denied" in message_text:
            return "permission_denied"
        return "backend_error"
    if "permission denied" in message_text:
        return "permission_denied"
    if "scanner returned no result" in message_text:
        return "missing_backend_result"
    return "other_incomplete"


def _malware_incomplete_group_label(group: str) -> str:
    return t(f"home.malware_result.incomplete_groups.{group}")


def _analysis_settings_snapshot(scan_options: dict[str, object]) -> dict[str, object]:
    return {
        "recursive": bool(scan_options.get("recursive")),
        "max_files": safe_int(scan_options.get("max_files", 5000)),
        "stale_days": safe_int(scan_options.get("stale_days", 30)),
        "large_file_bytes": safe_int(scan_options.get("large_file_bytes", 250 * 1024 * 1024)),
        "duplicate_detection": bool(scan_options.get("duplicate_detection")),
        "enable_malware_scan": bool(scan_options.get("enable_malware_scan")),
        "malware_scan_mode": str(scan_options.get("malware_scan_mode") or "standard"),
        "malware_scan_policy": str(scan_options.get("malware_scan_policy") or "standard"),
        "malware_scan_policy_version": "strict-v1"
        if str(scan_options.get("malware_scan_policy") or "standard").strip().lower() == "strict"
        else "standard-v1",
        "malware_scan_timeout_seconds": safe_int(scan_options.get("malware_scan_timeout_seconds", 30)),
        "malware_database_max_age_days": safe_int(scan_options.get("malware_database_max_age_days", 7)),
    }


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
    selected_backend = str(status.get("selected_backend") or "").strip()
    if selected_backend:
        details.append(t("malware.selected_backend", backend=selected_backend))
    engine_version = str(status.get("engine_version") or "").strip()
    details.append(
        t(
            "malware.engine_info",
            engine="ClamAV",
            version=engine_version or "-",
        )
    )
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


def _default_scan_options() -> dict[str, object]:
    return {
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
    }


def _default_processing_options() -> dict[str, object]:
    return {
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
    }


def _current_settings_draft() -> dict[str, object]:
    return {
        **_current_scan_options(),
        "ai_enabled": bool(st.session_state.get(SESSION_AI_ENABLED, False)),
        "enable_pdf_preview": bool(
            cast(dict[str, object], st.session_state.get(SESSION_PROCESSING_OPTIONS) or {}).get(
                "enable_pdf_preview", False
            )
        ),
        "enable_ocr": bool(
            cast(dict[str, object], st.session_state.get(SESSION_PROCESSING_OPTIONS) or {}).get("enable_ocr", False)
        ),
    }


def _current_scan_options() -> dict[str, object]:
    raw = st.session_state.get(SESSION_FOLDER_SCAN_OPTIONS)
    options = dict(_default_scan_options())
    if isinstance(raw, dict):
        options.update(raw)
    return options


def _current_processing_options(context: UIContext) -> dict[str, object]:
    raw = st.session_state.get(SESSION_PROCESSING_OPTIONS)
    options = dict(_default_processing_options())
    if isinstance(raw, dict):
        options.update(raw)
    options["pdf_ocr_max_pages"] = int(
        raw.get("pdf_ocr_max_pages", getattr(context.processor, "pdf_ocr_max_pages", 3))
        if isinstance(raw, dict)
        else getattr(context.processor, "pdf_ocr_max_pages", 3)
    )
    options["pdf_preview_max_pages"] = int(getattr(context.processor, "pdf_preview_max_pages", 1))
    return options


def _open_settings_dialog() -> None:
    st.session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT] = _current_settings_draft()
    open_dialog_state(SETTINGS_DIALOG_KEY)


def _discard_settings_draft() -> None:
    st.session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT] = _current_settings_draft()
    close_dialog_state(SETTINGS_DIALOG_KEY)


def _reset_settings_draft_to_defaults() -> None:
    st.session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT] = {
        **_default_scan_options(),
        "ai_enabled": False,
        "enable_pdf_preview": False,
        "enable_ocr": False,
    }


def _save_settings_draft(updated: dict[str, object], *, context: UIContext) -> None:
    normalized = dict(_default_scan_options())
    normalized.update(updated)
    normalized["stale_days"] = max(7, safe_int(normalized.get("stale_days")))
    normalized["large_file_bytes"] = max(10, safe_int(normalized.get("large_file_bytes"))) * 1024 * 1024
    normalized["max_files"] = max(100, safe_int(normalized.get("max_files")))
    normalized["recursive"] = bool(normalized.get("recursive"))
    normalized["duplicate_detection"] = bool(normalized.get("duplicate_detection"))
    normalized["enable_malware_scan"] = bool(normalized.get("enable_malware_scan"))
    normalized["malware_scan_timeout_seconds"] = max(5, safe_int(normalized.get("malware_scan_timeout_seconds")))
    normalized["malware_database_max_age_days"] = max(1, safe_int(normalized.get("malware_database_max_age_days")))
    normalized["malware_scan_mode"] = str(normalized.get("malware_scan_mode") or "standard")
    normalized["malware_scan_policy"] = str(normalized.get("malware_scan_policy") or "standard")
    normalized["malware_only_operation"] = bool(normalized.get("malware_only_operation"))
    processing_options = _current_processing_options(context)
    processing_options.update(
        {
            "enable_pdf_preview": bool(updated.get("enable_pdf_preview")),
            "enable_ocr": bool(updated.get("enable_ocr")),
            "pdf_preview_max_pages": int(getattr(context.processor, "pdf_preview_max_pages", 1)),
            "pdf_ocr_max_pages": int(getattr(context.processor, "pdf_ocr_max_pages", 3)),
        }
    )
    st.session_state[SESSION_FOLDER_SCAN_OPTIONS] = normalized
    st.session_state[SESSION_PROCESSING_OPTIONS] = processing_options
    st.session_state[SESSION_AI_ENABLED] = bool(updated.get("ai_enabled"))
    st.session_state[SESSION_FOLDER_SCAN_OPTIONS_DRAFT] = _current_settings_draft()
    close_dialog_state(SETTINGS_DIALOG_KEY)


def _scan_mode_label(value: object) -> str:
    return t(f"home.settings.scan_mode.{value or 'standard'}")


def _scan_policy_label(value: object) -> str:
    return t(f"home.settings.security_policy.{value or 'standard'}")


def _malware_primary_action_label(scan_options: dict[str, object]) -> str:
    if bool(scan_options.get("malware_only_operation")):
        return t("home.scan.primary_action_malware_only")
    if bool(scan_options.get("enable_malware_scan")):
        return t("home.scan.primary_action_secure")
    return t("home.scan.primary_action_organization")


def _safe_relative_path(root_path: object, path_value: object) -> str:
    root = Path(str(root_path or "")).expanduser()
    path_obj = Path(str(path_value or "")).expanduser()
    try:
        return str(path_obj.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except Exception:
        return path_obj.name or str(path_obj)


def _format_rate(bytes_per_second: float, files_per_second: float) -> str:
    if bytes_per_second > 0:
        return f"{human_bytes(int(bytes_per_second))}/s"
    return f"{files_per_second:.1f} files/s"


def _export_malware_result_csv(result: dict[str, object]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "overall_severity",
            "overall_status",
            "scan_mode",
            "coverage_scope",
            "relative_path",
            "path",
            "malware_status",
            "malware_verdict",
            "malware_scan_health",
            "malware_threat_name",
            "malware_backend",
            "malware_cache_hit",
            "malware_scanned_at",
            "malware_message",
        ],
    )
    writer.writeheader()
    summary = cast(dict[str, object], result.get("summary") or {})
    for row in cast(list[dict[str, object]], result.get("records") or []):
        writer.writerow(
            {
                "overall_severity": str(summary.get("overall_severity") or ""),
                "overall_status": str(summary.get("overall_status") or ""),
                "scan_mode": str(result.get("scan_mode") or ""),
                "coverage_scope": str(result.get("coverage_scope") or ""),
                "relative_path": _safe_relative_path(result.get("path"), row.get("path")),
                "path": str(row.get("path") or ""),
                "malware_status": str(row.get("malware_status") or ""),
                "malware_verdict": str(row.get("malware_verdict") or ""),
                "malware_scan_health": str(row.get("malware_scan_health") or ""),
                "malware_threat_name": str(row.get("malware_threat_name") or ""),
                "malware_backend": str(row.get("malware_backend") or ""),
                "malware_cache_hit": bool(row.get("malware_cache_hit")),
                "malware_scanned_at": str(row.get("malware_scanned_at") or ""),
                "malware_message": str(row.get("malware_message") or ""),
            }
        )
    return buffer.getvalue()


def _mark_dialog_dismissed(dialog_key: str, dismissed_key: str, result: dict[str, object] | None) -> None:
    if isinstance(result, dict):
        st.session_state[dismissed_key] = str(result.get("result_id") or "")
    close_dialog_state(dialog_key)


def _malware_result_dismiss_callback() -> None:
    _mark_dialog_dismissed(
        MALWARE_RESULT_DIALOG_KEY,
        SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID,
        cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_MALWARE_SCAN_RESULT)),
    )


def _analysis_result_dismiss_callback() -> None:
    _mark_dialog_dismissed(
        ANALYSIS_RESULT_DIALOG_KEY,
        SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID,
        cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_SCAN_CURRENT)),
    )


def _malware_completion_banner(summary: dict[str, object]) -> str:
    completed = safe_int(summary.get("completed_files"))
    total = max(0, safe_int(summary.get("result_records")))
    percentage = 0.0 if total <= 0 else (completed / total) * 100.0
    return t(
        "home.malware_result.completion",
        completed=completed,
        total=total,
        percent=f"{percentage:.1f}",
    )


def _malware_result_conclusion(summary: dict[str, object]) -> str:
    key = malware_result_conclusion_key(summary)
    if key.endswith(".suspicious"):
        return t(key, count=safe_int(summary.get("suspicious_files")))
    return t(key)


def _analysis_reviewable_bytes(records: list[dict[str, object]]) -> int:
    unique_sizes: dict[str, int] = {}
    for row in records:
        if not (
            bool(row.get("is_stale"))
            or bool(row.get("is_large"))
            or str(row.get("duplicate_type") or "").strip()
        ):
            continue
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        unique_sizes[canonical_path_key(path)] = safe_int(row.get("size_bytes"))
    return sum(unique_sizes.values())


def _maybe_auto_open_result_dialog(
    *,
    result: dict[str, object] | None,
    dialog_key: str,
    auto_open_key: str,
    dismissed_key: str,
) -> None:
    if not isinstance(result, dict):
        return
    result_id = str(result.get("result_id") or "")
    if not result_id:
        return
    if str(st.session_state.get(auto_open_key) or "") != result_id:
        return
    if str(st.session_state.get(dismissed_key) or "") == result_id:
        st.session_state[auto_open_key] = None
        return
    open_dialog_state(dialog_key)
    st.session_state[auto_open_key] = None


def _sync_analysis_with_malware_result(scan_options: dict[str, object]) -> dict[str, object] | None:
    analysis_result = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_SCAN_CURRENT))
    if not isinstance(analysis_result, dict):
        return None
    merged = merge_malware_scan_into_analysis(
        analysis_result,
        cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_MALWARE_SCAN_RESULT)),
        require_malware_scan=bool(scan_options.get("enable_malware_scan")),
        malware_scan_policy=str(scan_options.get("malware_scan_policy") or "standard"),
        malware_database_max_age_days=safe_int(scan_options.get("malware_database_max_age_days", 7)),
    )
    st.session_state[SESSION_FOLDER_SCAN_CURRENT] = merged
    return merged


def _render_settings_summary_card(scan_options: dict[str, object]) -> None:
    recursive_label = t("home.settings.subfolders_on") if bool(scan_options.get("recursive")) else t(
        "home.settings.subfolders_off"
    )
    cols = st.columns([1, 1, 1], gap="small")
    with cols[0]:
        st.markdown(
            f"""
            <div class="so-card so-card-secondary so-card-compact">
              <div class="card-title">{safe_display_text(t("home.settings.security_summary_title"))}</div>
              <div class="card-muted">{safe_display_text(t("home.settings.security_summary_inline", scan_mode=_scan_mode_label(scan_options.get("malware_scan_mode")), policy=_scan_policy_label(scan_options.get("malware_scan_policy")), malware_required=t("home.settings.malware_enabled" if bool(scan_options.get("enable_malware_scan")) else "home.settings.malware_disabled")))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with cols[1]:
        st.markdown(
            f"""
            <div class="so-card so-card-secondary so-card-compact">
              <div class="card-title">{safe_display_text(t("home.settings.organization_summary_title"))}</div>
              <div class="card-muted">{safe_display_text(t("home.settings.organization_summary_inline", subfolders=recursive_label, days=safe_int(scan_options.get("stale_days")), large_mb=max(1, safe_int(scan_options.get("large_file_bytes")) // (1024 * 1024)), max_files=safe_int(scan_options.get("max_files")), duplicate_detection=t("common.yes") if bool(scan_options.get("duplicate_detection")) else t("common.no")))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with cols[2]:
        if st.button(t("home.settings.edit_button"), key="open_settings_dialog_from_summary", use_container_width=True):
            _open_settings_dialog()
        st.caption(t("home.settings.no_auto_move_delete"))


def _current_primary_action_label(scan_options: dict[str, object]) -> str:
    if bool(scan_options.get("malware_only_operation")):
        return t("home.scan.primary_action_malware_only")
    if bool(scan_options.get("enable_malware_scan")):
        return t("home.scan.primary_action_secure")
    return t("home.scan.primary_action_organization")


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
    del context
    st.session_state.setdefault(SESSION_FOLDER_SCAN_OPTIONS, _current_scan_options())
    st.session_state.setdefault(SESSION_FOLDER_SCAN_OPTIONS_DRAFT, {})
    st.session_state.setdefault(SESSION_FOLDER_SETTINGS_DIALOG_OPEN, False)
    st.session_state.setdefault(SESSION_FOLDER_MALWARE_SCAN_RESULT, None)
    st.session_state.setdefault(SESSION_FOLDER_MALWARE_DIALOG_OPEN, False)
    st.session_state.setdefault(SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID, None)
    st.session_state.setdefault(SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID, None)
    st.session_state.setdefault(SESSION_FOLDER_ANALYSIS_DIALOG_OPEN, False)
    st.session_state.setdefault(SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID, None)
    st.session_state.setdefault(SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID, None)
    st.session_state.setdefault(SESSION_PROCESSING_OPTIONS, _default_processing_options())
    st.session_state.setdefault(SESSION_AI_ENABLED, False)
    st.session_state.setdefault(SESSION_DEBUG_MODE, False)


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
    language_options = get_language_options()
    current_language = get_current_language(st.session_state)
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
    header_action_columns = st.columns([1, 1, 1, 2, 2], gap="small")
    with header_action_columns[3]:
        selected_language = st.selectbox(
            t("home.settings.language_label"),
            options=language_options,
            index=language_options.index(current_language),
            format_func=get_language_label,
            key="header_ui_language",
            label_visibility="collapsed",
        )
        set_current_language(selected_language, st.session_state)
    with header_action_columns[4]:
        if st.button(t("home.settings.open_button"), key="open_settings_dialog_from_header", use_container_width=True):
            _open_settings_dialog()

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


def _render_settings_dialog_body(context: UIContext) -> None:
    draft = _current_settings_draft()
    raw_draft = st.session_state.get(SESSION_FOLDER_SCAN_OPTIONS_DRAFT)
    if isinstance(raw_draft, dict) and raw_draft:
        draft.update(raw_draft)

    st.caption(t("home.settings.dialog_description"))

    tab_organization, tab_security = st.tabs(
        [t("home.settings.organization_tab"), t("home.settings.security_tab")]
    )
    with st.form("folder_settings_form", clear_on_submit=False):
        with tab_organization:
            stale_days = st.slider(
                t("home.settings.organization.unused_days"),
                7,
                3650,
                safe_int(draft.get("stale_days", 364)),
                step=7,
            )
            large_file_mb = st.slider(
                t("home.settings.organization.large_file_mb"),
                10,
                2048,
                max(10, safe_int(draft.get("large_file_bytes")) // (1024 * 1024)),
                step=10,
            )
            recursive = st.checkbox(
                t("home.settings.organization.include_subfolders"),
                value=bool(draft.get("recursive", True)),
            )
            max_files = st.number_input(
                t("home.settings.organization.max_files"),
                min_value=100,
                max_value=200000,
                value=max(100, safe_int(draft.get("max_files", 5000))),
                step=500,
            )
            duplicate_detection = st.checkbox(
                t("home.settings.organization.duplicate_detection"),
                value=bool(draft.get("duplicate_detection", False)),
            )
            st.divider()
            st.caption(t("home.settings.organization.secondary_section"))
            ai_enabled = st.toggle(
                t("home.settings.organization.enable_ai_summary"),
                value=bool(draft.get("ai_enabled", False)),
            )
            enable_pdf_preview = st.checkbox(
                t("home.settings.organization.enable_pdf_preview"),
                value=bool(draft.get("enable_pdf_preview", False)),
            )
            enable_ocr = st.checkbox(
                t("home.settings.organization.enable_ocr"),
                value=bool(draft.get("enable_ocr", False)),
            )

        with tab_security:
            enable_malware_scan = st.checkbox(
                t("malware.enable_scan"),
                value=bool(draft.get("enable_malware_scan", False)),
            )
            malware_scan_mode = st.selectbox(
                t("home.settings.malware.scan_mode_label"),
                options=["fast", "standard", "full"],
                index=["fast", "standard", "full"].index(str(draft.get("malware_scan_mode", "standard"))),
                format_func=_scan_mode_label,
            )
            malware_scan_policy = st.selectbox(
                t("home.settings.malware.security_policy_label"),
                options=["standard", "strict"],
                index=["standard", "strict"].index(str(draft.get("malware_scan_policy", "standard"))),
                format_func=_scan_policy_label,
            )
            malware_scan_timeout_seconds = st.number_input(
                t("malware.timeout_seconds"),
                min_value=5,
                max_value=300,
                value=max(5, safe_int(draft.get("malware_scan_timeout_seconds", 30))),
                step=5,
            )
            malware_database_max_age_days = st.number_input(
                t("malware.database_max_age_days"),
                min_value=1,
                max_value=30,
                value=max(1, safe_int(draft.get("malware_database_max_age_days", 7))),
                step=1,
            )
            st.caption(t("home.settings.malware.engine_info"))
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

        submitted = st.form_submit_button(t("home.settings.save_button"), use_container_width=True)

    button_cols = st.columns(3, gap="small")
    with button_cols[0]:
        if st.button(t("home.settings.reset_button"), key="reset_folder_settings_dialog", use_container_width=True):
            _reset_settings_draft_to_defaults()
            st.rerun()
    with button_cols[1]:
        if st.button(t("home.settings.cancel_button"), key="cancel_folder_settings_dialog", use_container_width=True):
            _discard_settings_draft()
            st.rerun()
    with button_cols[2]:
        if st.button(t("malware.check_status"), key="dialog_check_clamav_status_button", use_container_width=True):
            st.session_state[CLAMAV_STATUS_SESSION_KEY] = _serialize_clamav_status(
                get_clamav_status(max(1, safe_int(draft.get("malware_database_max_age_days", 7))))
            )
            st.rerun()
        if st.button(t("malware.update_database"), key="dialog_update_clamav_database_button", use_container_width=True):
            ok, message = update_clamav_database()
            st.session_state[CLAMAV_UPDATE_RESULT_SESSION_KEY] = {"ok": ok, "message": message}
            st.session_state[CLAMAV_STATUS_SESSION_KEY] = _serialize_clamav_status(
                get_clamav_status(max(1, safe_int(draft.get("malware_database_max_age_days", 7))))
            )
            st.rerun()

    if submitted:
        _save_settings_draft(
            {
                "stale_days": int(stale_days),
                "large_file_bytes": int(large_file_mb),
                "recursive": bool(recursive),
                "max_files": int(max_files),
                "duplicate_detection": bool(duplicate_detection),
                "enable_malware_scan": bool(enable_malware_scan),
                "malware_scan_mode": malware_scan_mode,
                "malware_scan_policy": malware_scan_policy,
                "malware_scan_timeout_seconds": int(malware_scan_timeout_seconds),
                "malware_database_max_age_days": int(malware_database_max_age_days),
                "malware_only_operation": bool(draft.get("malware_only_operation", False)),
                "ai_enabled": bool(ai_enabled),
                "enable_pdf_preview": bool(enable_pdf_preview),
                "enable_ocr": bool(enable_ocr),
            },
            context=context,
        )
        st.rerun()


def _render_home_dialogs(
    context: UIContext,
    *,
    warning_messages: list[str] | None = None,
    report_payload: str | None = None,
    records: list[dict[str, object]] | None = None,
    candidates: list[dict[str, object]] | None = None,
) -> None:
    reset_dialog_render_cycle()
    render_dialog(
        key=SETTINGS_DIALOG_KEY,
        title=t("home.settings.dialog_title"),
        render_body=lambda: _render_settings_dialog_body(context),
        width="medium",
        on_dismiss=_discard_settings_draft,
        dismiss_state_keys=(SESSION_FOLDER_SCAN_OPTIONS_DRAFT, CLAMAV_UPDATE_RESULT_SESSION_KEY),
    )
    render_dialog(
        key=MALWARE_RESULT_DIALOG_KEY,
        title=t("home.malware_result.dialog_title"),
        render_body=_render_malware_result_dialog_body,
        width="large",
        on_dismiss=_malware_result_dismiss_callback,
    )
    render_dialog(
        key=ANALYSIS_RESULT_DIALOG_KEY,
        title=t("home.analysis_result.dialog_title"),
        render_body=_render_analysis_result_dialog_body,
        width="large",
        on_dismiss=_analysis_result_dismiss_callback,
    )
    render_dialog(
        key=HELP_DIALOG_KEY,
        title=t("home.dialogs.help_title"),
        render_body=_render_help_dialog_body,
        width="medium",
    )
    render_dialog(
        key=SAFETY_DIALOG_KEY,
        title=t("home.dialogs.safety_title"),
        render_body=lambda: st.info(t("home.safety_notice")),
        width="medium",
    )
    render_dialog(
        key=WORKFLOW_DIALOG_KEY,
        title=t("home.dialogs.workflow_title"),
        render_body=_render_process_steps,
        width="medium",
    )
    render_dialog(
        key=WARNINGS_DIALOG_KEY,
        title=t("home.dialogs.warnings_title"),
        render_body=lambda: _render_warning_messages(warning_messages or []),
        width="medium",
    )
    render_dialog(
        key=REPORT_DIALOG_KEY,
        title=t("home.dialogs.report_preview_title"),
        render_body=lambda: st.code((report_payload or "")[:4000], language="markdown"),
        width="large",
    )
    render_dialog(
        key=STATS_DIALOG_KEY,
        title=t("home.dialogs.stats_title"),
        render_body=lambda: _render_stats_dialog_body(records or [], candidates or []),
        width="medium",
    )
    render_dialog(
        key=PATHS_DIALOG_KEY,
        title=t("home.dialogs.paths_title"),
        render_body=_render_selected_path_details,
        width="large",
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


def _store_malware_scan_result(scan_options: dict[str, object], result: dict[str, object]) -> None:
    st.session_state[SESSION_FOLDER_MALWARE_SCAN_RESULT] = result
    result_id = str(result.get("result_id") or "")
    st.session_state[SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID] = result_id
    if result_id:
        st.session_state[SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID] = ""
    analysis_result = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_SCAN_CURRENT))
    if isinstance(analysis_result, dict) and str(analysis_result.get("path") or "") == str(result.get("path") or ""):
        st.session_state[SESSION_FOLDER_SCAN_CURRENT] = merge_malware_scan_into_analysis(
            analysis_result,
            result,
            require_malware_scan=bool(scan_options.get("enable_malware_scan")),
            malware_scan_policy=str(scan_options.get("malware_scan_policy") or "standard"),
            malware_database_max_age_days=safe_int(scan_options.get("malware_database_max_age_days", 7)),
        )


def _store_analysis_result(scan_options: dict[str, object], result: dict[str, object]) -> None:
    merged = merge_malware_scan_into_analysis(
        result,
        cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_MALWARE_SCAN_RESULT)),
        require_malware_scan=bool(scan_options.get("enable_malware_scan")),
        malware_scan_policy=str(scan_options.get("malware_scan_policy") or "standard"),
        malware_database_max_age_days=safe_int(scan_options.get("malware_database_max_age_days", 7)),
    )
    merged["analysis_settings"] = _analysis_settings_snapshot(scan_options)
    st.session_state[SESSION_FOLDER_SCAN_CURRENT] = merged
    st.session_state[SESSION_FOLDER_REPORT_SNAPSHOT] = build_report_snapshot(merged)
    st.session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] = None
    st.session_state[SESSION_FOLDER_RESTORE_RESULT] = None
    st.session_state[SESSION_FOLDER_SELECTED_PATHS] = []
    result_id = str(merged.get("result_id") or "")
    st.session_state[SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID] = result_id
    if result_id:
        st.session_state[SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID] = ""


def _render_folder_action_panel(
    context: UIContext,
    *,
    folder_path: str,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    duplicate_detection: bool,
    enable_malware_scan: bool,
    malware_scan_mode: str,
    malware_scan_timeout_seconds: int,
    malware_database_max_age_days: int,
    malware_scan_policy: str,
) -> None:
    current_status = _clamav_status_from_session() or _serialize_clamav_status(get_clamav_status(malware_database_max_age_days))
    st.markdown(
        f"""
        <div class="so-card so-card-compact">
          <div class="card-title">{safe_display_text(t("home.scan.title"))}</div>
          <div class="card-muted">{safe_display_text(t("home.scan.description"))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.text_input(
        t("home.scan.input_label"),
        value=folder_path,
        placeholder=t("home.scan.input_placeholder"),
        key=SESSION_FOLDER_SCAN_PATH,
    )
    action_cols = st.columns(2, gap="medium")
    with action_cols[0], st.container(border=True):
        st.markdown(f"### {t('home.malware_action.title')}")
        st.caption(t("home.malware_action.description"))
        st.caption(
            t(
                "home.malware_action.summary",
                scan_mode=_scan_mode_label(malware_scan_mode),
                policy=_scan_policy_label(malware_scan_policy),
                backend=str(current_status.get("selected_backend") or "-"),
                database_status=t(
                    _CLAMAV_STATUS_LABEL_KEYS.get(
                        str(current_status.get("availability") or "unknown"),
                        "malware.status_unknown",
                    )
                ),
                database_age=str(current_status.get("database_age_days") if current_status.get("database_age_days") is not None else "-"),
            )
        )
        st.caption(_current_primary_action_label(_current_scan_options()))
        if st.button(
            t("home.malware_action.run_button"),
            key="run_folder_malware_scan",
            type="primary",
            use_container_width=True,
        ):
            try:
                progress_bar = st.progress(0)
                status_text = st.empty()

                def on_malware_progress(processed: int, total: int, _stage: str) -> None:
                    progress_bar.progress(min(1.0, processed / max(1, total)))
                    status_text.text(t("home.malware_action.progress", count=processed))

                result = scan_folder_malware(
                    folder_path,
                    recursive=recursive,
                    max_files=max_files,
                    malware_scan_mode=malware_scan_mode,
                    malware_scan_timeout_seconds=malware_scan_timeout_seconds,
                    malware_database_max_age_days=malware_database_max_age_days,
                    malware_scan_policy=malware_scan_policy,
                    progress_callback=on_malware_progress,
                    storage=context.storage,
                )
                progress_bar.progress(1.0)
                status_text.text(t("home.malware_action.complete"))
                _store_malware_scan_result(_current_scan_options(), result)
                st.rerun()
            except ScanPathError as exc:
                st.error(str(exc))
            except PermissionError:
                st.error(t("home.scan.permission_denied"))
            except FolderOrganizerError as exc:
                st.error(str(exc))
            except Exception as exc:
                handle_ui_exception(t("home.malware_action.failed"), exc)
    with action_cols[1], st.container(border=True):
        st.markdown(f"### {t('home.organization_action.title')}")
        st.caption(t("home.organization_action.description"))
        st.caption(
            t(
                "home.organization_action.summary",
                days=stale_days,
                large_mb=max(1, int(large_file_bytes / (1024 * 1024))),
                subfolders=t("home.settings.subfolders_on") if recursive else t("home.settings.subfolders_off"),
                max_files=max_files,
                duplicate_detection=t("common.yes") if duplicate_detection else t("common.no"),
            )
        )
        st.caption(_current_primary_action_label(_current_scan_options()))
        if st.button(
            t("home.organization_action.run_button"),
            key="run_folder_organization_analysis",
            type="primary",
            use_container_width=True,
        ):
            try:
                progress_bar = st.progress(0)
                status_text = st.empty()

                def on_analysis_progress(scanned: int, cap: int) -> None:
                    progress_bar.progress(min(1.0, scanned / max(1, cap)))
                    status_text.text(t("home.organization_action.progress", count=scanned))

                result = scan_folder(
                    folder_path,
                    recursive=recursive,
                    max_files=max_files,
                    stale_days=stale_days,
                    large_file_bytes=large_file_bytes,
                    duplicate_detection=duplicate_detection,
                    enable_malware_scan=False,
                    malware_scan_timeout_seconds=malware_scan_timeout_seconds,
                    malware_database_max_age_days=malware_database_max_age_days,
                    malware_scan_policy=malware_scan_policy,
                    progress_callback=on_analysis_progress,
                )
                result["result_id"] = uuid.uuid4().hex
                progress_bar.progress(1.0)
                status_text.text(t("home.organization_action.complete"))
                _store_analysis_result(_current_scan_options(), result)
                st.rerun()
            except ScanPathError as exc:
                st.error(str(exc))
            except PermissionError:
                st.error(t("home.scan.permission_denied"))
            except FolderOrganizerError as exc:
                st.error(str(exc))
            except Exception as exc:
                handle_ui_exception(t("home.organization_action.failed"), exc)


def _render_malware_result_summary_card(result: dict[str, object]) -> None:
    summary = cast(dict[str, object], result.get("summary") or {})
    st.markdown(
        f"""
        <div class="so-card so-card-secondary so-card-compact">
          <div class="card-title">{safe_display_text(t("home.malware_result.summary_title"))}</div>
          <div class="card-muted">{safe_display_text(t("home.malware_result.summary_inline", clean=summary.get("clean_files", 0), suspicious=summary.get("suspicious_files", 0), infected=summary.get("infected_files", 0), incomplete=summary.get("incomplete_or_failed_scans", 0)))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button(
        t("home.malware_result.reopen_button"),
        key="reopen_folder_malware_result_dialog",
        use_container_width=True,
    ):
        open_dialog_state(MALWARE_RESULT_DIALOG_KEY)


def _render_analysis_result_summary_card(result: dict[str, object]) -> None:
    records = [item for item in cast(list[object], result.get("records") or []) if isinstance(item, dict)]
    candidates = [item for item in records if item.get("candidate_reasons")]
    duplicate_files = sum(1 for item in records if str(item.get("duplicate_type") or "").strip())
    st.markdown(
        f"""
        <div class="so-card so-card-secondary so-card-compact">
          <div class="card-title">{safe_display_text(t("home.analysis_result.summary_title"))}</div>
          <div class="card-muted">{safe_display_text(t("home.analysis_result.summary_inline", unused=cast(dict[str, object], result.get("stats")).get("stale_candidates", 0) if isinstance(result.get("stats"), dict) else 0, large=cast(dict[str, object], result.get("stats")).get("large_candidates", 0) if isinstance(result.get("stats"), dict) else 0, duplicate_files=duplicate_files, reclaimable=human_bytes(sum(safe_int(item.get("size_bytes")) for item in candidates))))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button(
        t("home.analysis_result.reopen_button"),
        key="reopen_folder_analysis_result_dialog",
        use_container_width=True,
    ):
        open_dialog_state(ANALYSIS_RESULT_DIALOG_KEY)


def _render_malware_result_dialog_body() -> None:
    result = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_MALWARE_SCAN_RESULT))
    if not isinstance(result, dict):
        st.info(t("home.malware_result.empty"))
        return
    summary = cast(dict[str, object], result.get("summary") or {})
    records = [item for item in cast(list[object], result.get("records") or []) if isinstance(item, dict)]
    conclusion = _malware_result_conclusion(summary)
    severity = malware_result_severity(summary)
    if severity == "danger":
        st.error(conclusion)
    elif severity == "warning":
        st.warning(conclusion)
    else:
        st.success(conclusion)
    st.caption(_malware_completion_banner(summary))
    tabs = st.tabs(
        [
            t("home.malware_result.tabs.summary"),
            t("home.malware_result.tabs.blocked"),
            t("home.malware_result.tabs.incomplete"),
            t("home.malware_result.tabs.all_files"),
            t("home.malware_result.tabs.technical"),
        ]
    )
    metrics = [
        ("enumerated_files", "home.malware_result.metrics.enumerated_files"),
        ("completed_files", "home.malware_result.metrics.completed_files"),
        ("clean_files", "home.malware_result.metrics.clean_files"),
        ("suspicious_files", "home.malware_result.metrics.suspicious_files"),
        ("infected_files", "home.malware_result.metrics.infected_files"),
        ("incomplete_files", "home.malware_result.metrics.incomplete_files"),
        ("cache_hits", "home.malware_result.metrics.cache_hits"),
        ("files_sent_to_scanner", "home.malware_result.metrics.actually_scanned"),
    ]
    with tabs[0]:
        metric_columns = st.columns(4, gap="small")
        for index, (field, key) in enumerate(metrics):
            with metric_columns[index % len(metric_columns)]:
                st.metric(t(key), safe_int(summary.get(field)))
        st.caption(
            t(
                "home.malware_result.coverage",
                mode=_scan_mode_label(result.get("scan_mode")),
                coverage=str(result.get("coverage_scope") or summary.get("coverage_scope") or "-"),
                recursive=t("common.yes") if bool(result.get("recursive")) else t("common.no"),
                max_files=safe_int(result.get("max_files")),
                truncated=t("common.yes") if bool(summary.get("limit_reached")) else t("common.no"),
            )
        )
        st.caption(
            t(
                "home.malware_result.performance",
                total_bytes=human_bytes(safe_int(summary.get("total_bytes"))),
                elapsed=f"{float(cast(float | int | str, summary.get('elapsed_seconds') or 0.0)):.2f}s",
                throughput=_format_rate(
                    float(cast(float | int | str, summary.get("bytes_per_second") or 0.0)),
                    float(cast(float | int | str, summary.get("files_per_second") or 0.0)),
                ),
            )
        )
    with tabs[1]:
        blocked_rows = [
            {
                t("home.malware_result.columns.file_name"): str(row.get("name") or Path(str(row.get("path") or "")).name),
                t("home.malware_result.columns.relative_path"): _safe_relative_path(result.get("path"), row.get("path")),
                t("home.malware_result.columns.verdict"): _malware_scan_label(row.get("malware_status")),
                t("home.malware_result.columns.health"): _malware_scan_health_label(row.get("malware_scan_health")),
                t("home.malware_result.columns.threat"): str(row.get("malware_threat_name") or ""),
                t("home.malware_result.columns.message"): str(row.get("malware_message") or ""),
            }
            for row in records
            if str(row.get("malware_status") or "") in {"suspicious", "infected"}
        ]
        if blocked_rows:
            st.dataframe(blocked_rows, use_container_width=True, hide_index=True)
        else:
            st.info(t("home.malware_result.no_blocked"))
    with tabs[2]:
        incomplete_rows = [
            row for row in records if str(row.get("malware_scan_health") or "") != "ok"
        ]
        grouped_causes: dict[str, int] = {}
        for row in incomplete_rows:
            group = _malware_incomplete_group(row.get("malware_scan_health"), row.get("malware_message"))
            grouped_causes[group] = grouped_causes.get(group, 0) + 1
        if grouped_causes:
            st.dataframe(
                [
                    {
                        t("home.malware_result.columns.cause"): _malware_incomplete_group_label(group),
                        t("home.malware_result.columns.count"): count,
                    }
                    for group, count in grouped_causes.items()
                ],
                use_container_width=True,
                hide_index=True,
            )
            st.dataframe(
                [
                    {
                        t("home.malware_result.columns.file_name"): str(row.get("name") or Path(str(row.get("path") or "")).name),
                        t("home.malware_result.columns.relative_path"): _safe_relative_path(result.get("path"), row.get("path")),
                        t("home.malware_result.columns.cause"): _malware_incomplete_group_label(
                            _malware_incomplete_group(row.get("malware_scan_health"), row.get("malware_message"))
                        ),
                        t("home.malware_result.columns.message"): str(row.get("malware_message") or ""),
                    }
                    for row in incomplete_rows
                ],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info(t("home.malware_result.no_incomplete"))
    with tabs[3]:
        all_rows = [
            {
                t("home.malware_result.columns.file_name"): str(row.get("name") or Path(str(row.get("path") or "")).name),
                t("home.malware_result.columns.relative_path"): _safe_relative_path(result.get("path"), row.get("path")),
                t("home.malware_result.columns.verdict"): _malware_scan_label(row.get("malware_status")),
                t("home.malware_result.columns.health"): _malware_scan_health_label(row.get("malware_scan_health")),
                t("home.malware_result.columns.threat"): str(row.get("malware_threat_name") or ""),
                t("home.malware_result.columns.cache_hit"): t("common.yes") if bool(row.get("malware_cache_hit")) else t("common.no"),
                t("home.malware_result.columns.scanned_at"): format_timestamp_for_display(row.get("malware_scanned_at")),
                t("home.malware_result.columns.message"): str(row.get("malware_message") or ""),
            }
            for row in records
        ]
        st.dataframe(all_rows, use_container_width=True, hide_index=True)
    with tabs[4]:
        st.dataframe(
            [
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.mode"), t("home.malware_result.columns.value"): _scan_mode_label(result.get("scan_mode"))},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.coverage"), t("home.malware_result.columns.value"): str(result.get("coverage_scope") or summary.get("coverage_scope") or "-")},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.recursive"), t("home.malware_result.columns.value"): t("common.yes") if bool(result.get("recursive")) else t("common.no")},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.max_files"), t("home.malware_result.columns.value"): safe_int(result.get("max_files"))},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.truncated"), t("home.malware_result.columns.value"): t("common.yes") if bool(summary.get("limit_reached")) else t("common.no")},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.backend"), t("home.malware_result.columns.value"): str(summary.get("backend") or "-")},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.engine_version"), t("home.malware_result.columns.value"): str(summary.get("engine_version") or "-")},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.database_version"), t("home.malware_result.columns.value"): str(summary.get("database_version") or "-")},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.database_date"), t("home.malware_result.columns.value"): str(summary.get("database_date") or "-")},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.elapsed"), t("home.malware_result.columns.value"): f"{float(cast(float | int | str, summary.get('elapsed_seconds') or 0.0)):.2f}s"},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.total_bytes"), t("home.malware_result.columns.value"): human_bytes(safe_int(summary.get("scanned_bytes") or summary.get("total_bytes")))},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.throughput"), t("home.malware_result.columns.value"): _format_rate(float(cast(float | int | str, summary.get("bytes_per_second") or 0.0)), float(cast(float | int | str, summary.get("files_per_second") or 0.0)))},
                {t("home.malware_result.columns.metric"): t("home.malware_result.technical.scanned_at"), t("home.malware_result.columns.value"): format_timestamp_for_display(result.get("scanned_at"))},
            ],
            use_container_width=True,
            hide_index=True,
        )
        with st.expander(t("home.malware_result.full_paths")):
            for row in records:
                st.code(str(row.get("path") or ""), language=None)
    st.download_button(
        t("home.malware_result.export_button"),
        _export_malware_result_csv(result),
        file_name="smart-organizer-malware-scan.csv",
        mime="text/csv",
        use_container_width=True,
    )


def _render_analysis_result_dialog_body() -> None:
    result = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_SCAN_CURRENT))
    if not isinstance(result, dict):
        st.info(t("home.analysis_result.empty"))
        return
    records = [item for item in cast(list[object], result.get("records") or []) if isinstance(item, dict)]
    stale_rows = [item for item in records if bool(item.get("is_stale"))]
    large_rows = [item for item in records if bool(item.get("is_large"))]
    duplicate_rows = [item for item in records if str(item.get("duplicate_type") or "").strip()]
    stats = cast(dict[str, object], result.get("stats") or {})
    analysis_settings = cast(dict[str, object], result.get("analysis_settings") or {})
    duplicate_detection_enabled = bool(analysis_settings.get("duplicate_detection"))
    unique_candidate_bytes = _analysis_reviewable_bytes(records)
    duplicate_groups = len(
        {
            str(item.get("duplicate_group_id") or "")
            for item in duplicate_rows
            if str(item.get("duplicate_group_id") or "").strip()
        }
    )
    tabs = st.tabs(
        [
            t("home.analysis_result.tabs.summary"),
            t("home.analysis_result.tabs.candidates"),
            t("home.analysis_result.tabs.duplicates"),
            t("home.analysis_result.tabs.technical"),
        ]
    )
    with tabs[0]:
        metric_pairs = [
            (t("home.analysis_result.metrics.total_files"), safe_int(stats.get("scanned_files"))),
            (t("home.analysis_result.metrics.unique_candidates"), len([row for row in records if row.get("candidate_reasons")])),
            (t("home.analysis_result.metrics.unused_candidates"), len(stale_rows)),
            (t("home.analysis_result.metrics.large_candidates"), len(large_rows)),
            (t("home.analysis_result.metrics.duplicate_groups"), duplicate_groups),
            (t("home.analysis_result.metrics.duplicate_files"), len(duplicate_rows)),
            (t("home.analysis_result.metrics.unique_candidate_bytes"), human_bytes(unique_candidate_bytes)),
            (t("home.analysis_result.metrics.elapsed"), f"{float(cast(float | int | str, result.get('elapsed_seconds') or 0.0)):.2f}s"),
        ]
        metric_columns = st.columns(4, gap="small")
        for index, (label, value) in enumerate(metric_pairs):
            with metric_columns[index % len(metric_columns)]:
                st.metric(label, value)
        st.caption(t("home.analysis_result.review_notice"))
        if duplicate_detection_enabled:
            st.caption(t("home.analysis_result.duplicate_enabled"))
        else:
            st.info(t("home.analysis_result.duplicate_disabled"))
    with tabs[1]:
        candidate_rows = [
            {
                t("home.analysis_result.columns.file_name"): str(row.get("name") or Path(str(row.get("path") or "")).name),
                t("home.analysis_result.columns.relative_path"): _safe_relative_path(result.get("path"), row.get("path")),
                t("home.analysis_result.columns.size"): human_bytes(safe_int(row.get("size_bytes"))),
                t("home.analysis_result.columns.modified_time"): format_timestamp_for_display(row.get("mtime")),
                t("home.analysis_result.columns.candidate_reasons"): _candidate_reason_text(row),
                t("home.analysis_result.columns.recommendation"): recommendation_display_label(row.get("recommendation")),
                t("home.analysis_result.columns.risk_level"): risk_display_label(row.get("risk_level")),
            }
            for row in records
            if row.get("candidate_reasons")
        ]
        if candidate_rows:
            st.dataframe(candidate_rows, use_container_width=True, hide_index=True)
        else:
            st.info(t("home.analysis_result.no_rows"))
    with tabs[2]:
        duplicate_table_rows = [
            {
                t("home.analysis_result.columns.file_name"): str(row.get("name") or Path(str(row.get("path") or "")).name),
                t("home.analysis_result.columns.relative_path"): _safe_relative_path(result.get("path"), row.get("path")),
                t("home.analysis_result.columns.size"): human_bytes(safe_int(row.get("size_bytes"))),
                t("home.analysis_result.columns.modified_time"): format_timestamp_for_display(row.get("mtime")),
                t("home.analysis_result.columns.duplicate_info"): _duplicate_type_label(row.get("duplicate_type")),
                t("home.analysis_result.columns.candidate_reasons"): _candidate_reason_text(row),
            }
            for row in duplicate_rows
        ]
        if duplicate_table_rows:
            st.dataframe(duplicate_table_rows, use_container_width=True, hide_index=True)
        elif duplicate_detection_enabled:
            st.info(t("home.analysis_result.no_rows"))
        else:
            st.info(t("home.analysis_result.duplicate_disabled"))
    with tabs[3]:
        warnings: list[str] = []
        warnings.extend(_coerce_message_list(result.get("errors")))
        warnings.extend(_coerce_message_list(result.get("notes")))
        if bool(result.get("limit_reached")):
            warnings.append(t("home.analysis_result.max_files_warning", count=safe_int(result.get("max_files"))))
        if warnings:
            for message in warnings:
                st.warning(message)
        else:
            st.info(t("home.analysis_result.no_warnings"))
    if st.button(t("home.analysis_result.go_to_review"), key="navigate_to_review_from_analysis_dialog", use_container_width=True):
        st.session_state[SESSION_MAIN_TAB_OVERRIDE] = "review_results"
        close_dialog_state(ANALYSIS_RESULT_DIALOG_KEY)
        st.rerun()

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
    scan_options = _current_scan_options()
    stale_days = safe_int(scan_options.get("stale_days", 365))
    recursive = bool(scan_options.get("recursive", True))
    max_files = safe_int(scan_options.get("max_files", 5000))
    large_file_bytes = safe_int(scan_options.get("large_file_bytes", 250 * 1024 * 1024))
    duplicate_detection = bool(scan_options.get("duplicate_detection", False))
    enable_malware_scan = bool(scan_options.get("enable_malware_scan", False))
    malware_scan_mode = str(scan_options.get("malware_scan_mode") or "standard")
    malware_scan_timeout_seconds = safe_int(scan_options.get("malware_scan_timeout_seconds", 30))
    malware_database_max_age_days = safe_int(scan_options.get("malware_database_max_age_days", 7))
    malware_scan_policy = str(scan_options.get("malware_scan_policy") or "standard")
    folder_path = str(st.session_state.get(SESSION_FOLDER_SCAN_PATH) or "")
    current_scan = _sync_analysis_with_malware_result(scan_options)
    malware_result = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_MALWARE_SCAN_RESULT))
    with st.container(key="home_shell", border=False):
        with st.container(key="home_viewport", height="stretch", border=False):
            _render_home_header()
            _render_settings_summary_card(scan_options)
            _render_folder_action_panel(
                context,
                folder_path=folder_path,
                recursive=recursive,
                max_files=max_files,
                stale_days=stale_days,
                large_file_bytes=large_file_bytes,
                duplicate_detection=duplicate_detection,
                enable_malware_scan=enable_malware_scan,
                malware_scan_mode=malware_scan_mode,
                malware_scan_timeout_seconds=malware_scan_timeout_seconds,
                malware_database_max_age_days=malware_database_max_age_days,
                malware_scan_policy=malware_scan_policy,
            )
            _maybe_auto_open_result_dialog(
                result=malware_result,
                dialog_key=MALWARE_RESULT_DIALOG_KEY,
                auto_open_key=SESSION_FOLDER_MALWARE_AUTO_OPEN_RESULT_ID,
                dismissed_key=SESSION_FOLDER_MALWARE_DISMISSED_RESULT_ID,
            )
            _maybe_auto_open_result_dialog(
                result=current_scan,
                dialog_key=ANALYSIS_RESULT_DIALOG_KEY,
                auto_open_key=SESSION_FOLDER_ANALYSIS_AUTO_OPEN_RESULT_ID,
                dismissed_key=SESSION_FOLDER_ANALYSIS_DISMISSED_RESULT_ID,
            )

            summary_cols = st.columns(3, gap="medium")
            with summary_cols[0]:
                if isinstance(malware_result, dict):
                    _render_malware_result_summary_card(malware_result)
            with summary_cols[1]:
                if isinstance(current_scan, dict):
                    _render_analysis_result_summary_card(current_scan)
            with summary_cols[2]:
                _render_quarantine_panel(
                    folder_path=folder_path,
                    current_scan=cast(dict[str, object], current_scan or {}),
                    recursive=recursive,
                    max_files=max_files,
                    stale_days=stale_days,
                    large_file_bytes=large_file_bytes,
                    enable_malware_scan=enable_malware_scan,
                    malware_scan_timeout_seconds=malware_scan_timeout_seconds,
                    malware_database_max_age_days=malware_database_max_age_days,
                )

            scan = current_scan
            warning_messages: list[str] = []
            records: list[dict[str, object]] = []
            candidates: list[dict[str, object]] = []
            current_quarantine_items: list[dict[str, object]] = []
            report_payload = ""
            if isinstance(scan, dict):
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
                    enable_malware_scan=bool(scan.get("enable_malware_scan")),
                    malware_scan_timeout_seconds=malware_scan_timeout_seconds,
                    malware_database_max_age_days=malware_database_max_age_days,
                )
            else:
                st.info(t("home.organization_action.empty"))

            _render_home_dialogs(
                context,
                warning_messages=warning_messages,
                report_payload=report_payload,
                records=records,
                candidates=candidates,
            )
        with st.container(key="home_footer", border=False):
            st.caption(f"{APP_NAME} v{__version__}")
