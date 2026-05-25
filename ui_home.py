from __future__ import annotations

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
from ui_common import (
    UIContext,
    card_close,
    card_open,
    format_timestamp_for_display,
    handle_ui_exception,
    is_debug,
    render_safe_html_text,
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
_REASON_LABEL_KEYS = {
    "long_unused": "home.candidates.reason_long_unused",
    "large_file": "home.candidates.reason_large_file",
    "duplicate_candidate": "home.candidates.reason_duplicate_candidate",
    "temp_cache_log": "home.candidates.reason_temp_cache_log",
    "low_confidence": "home.candidates.reason_low_confidence",
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
    return cache_dependency_status(st.session_state, context.processor.get_dependency_status())


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

    st.sidebar.markdown(
        f"**{t('sidebar.quick_flow_title')}**\n"
        f"- {t('sidebar.quick_flow.scan')}\n"
        f"- {t('sidebar.quick_flow.preview')}\n"
        f"- {t('sidebar.quick_flow.quarantine')}\n"
        f"- {t('sidebar.quick_flow.restore')}"
    )

    with st.sidebar.expander(t("sidebar.scan_settings_title"), expanded=True):
        stale_days = st.slider(t("sidebar.stale_days"), 7, 3650, 365, step=7)
        large_file_mb = st.slider(t("sidebar.large_file_mb"), 10, 2048, 250, step=10)
        recursive = st.checkbox(t("sidebar.scan_subfolders"), value=True, key="folder_recursive")
        max_files = st.number_input(t("sidebar.max_files"), min_value=100, max_value=200000, value=5000, step=500)
        st.session_state[SESSION_FOLDER_SCAN_OPTIONS] = {
            "stale_days": int(stale_days),
            "large_file_bytes": int(large_file_mb) * 1024 * 1024,
            "recursive": bool(recursive),
            "max_files": int(max_files),
        }

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
        st.caption(t("sidebar.upload_limit", size=f"{int(context.max_upload_bytes / (1024 * 1024))} MB"))

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
        if st.button(t("sidebar.check_dependencies"), key="check_dependencies_button"):
            dependency_status = refresh_dependency_status(context)
            st.success(t("sidebar.dependency_check_success"))
        elif dependency_status is None:
            st.caption(t("sidebar.dependency_check_hint"))

        if dependency_status is not None:
            st.markdown(f"**{t('sidebar.dependency_check_title')}**")
            render_dependency_status(dependency_status)

        if is_debug():
            st.caption(t("sidebar.processing_options"))
            st.json(st.session_state.get(SESSION_PROCESSING_OPTIONS) or {})

    with st.sidebar.expander(t("sidebar.development_info_title"), expanded=False):
        st.markdown(
            f"- {t('sidebar.workspace.project_root')}: `{context.project_root}`\n"
            f"- {t('sidebar.workspace.uploads')}: `{context.upload_dir}`\n"
            f"- {t('sidebar.workspace.repo')}: `{context.repo_root}`\n"
            f"- {t('sidebar.workspace.database')}: `{context.db_path}`"
        )


def _render_candidate_editor(context: UIContext, candidates: list[dict[str, object]]) -> list[str]:
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
    if st.button(t("home.candidates.select_all_preview"), key="select_all_candidates_for_preview"):
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = [str(item.get("path")) for item in candidates]
    if st.button(t("home.candidates.select_safe_review"), key="select_safe_review_candidates"):
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = [
            str(item.get("path")) for item in candidates if item.get("risk_level") == "safe_to_review"
        ]
    if st.button(t("home.candidates.clear_selection"), key="clear_candidate_selection"):
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = []

    rows: list[dict[str, object]] = []
    for item in candidates:
        rows.append(
            {
                "select": False,
                "name": item.get("name"),
                "recommendation": recommendation_display_label(item.get("recommendation")),
                "risk_level": risk_display_label(item.get("risk_level")),
                "reasons": "、".join(_localized_reason_list(item)),
                "size": human_bytes(int(cast(int, item.get("size_bytes") or 0))),
                "last_modified": format_timestamp_for_display(item.get("mtime")),
                "path": item.get("path"),
            }
        )

    selected_paths = [str(path) for path in cast(list[object], st.session_state.get(SESSION_FOLDER_SELECTED_PATHS, []))]
    if context.pandas is not None:
        df = context.pandas.DataFrame(rows)
        if selected_paths:
            df["select"] = df["path"].isin(selected_paths)
        edited = st.data_editor(
            df,
            hide_index=True,
            use_container_width=True,
            column_config={
                "select": st.column_config.CheckboxColumn(t("home.candidates.table.select"), width="small"),
                "name": st.column_config.TextColumn(t("home.candidates.table.name"), width="medium"),
                "recommendation": st.column_config.TextColumn(t("home.candidates.table.recommendation"), width="small"),
                "risk_level": st.column_config.TextColumn(t("home.candidates.table.risk_level"), width="small"),
                "reasons": st.column_config.TextColumn(t("home.candidates.table.reasons"), width="large"),
                "size": st.column_config.TextColumn(t("home.candidates.table.size"), width="small"),
                "last_modified": st.column_config.TextColumn(t("home.candidates.table.last_modified"), width="medium"),
                "path": st.column_config.TextColumn(t("home.candidates.table.path"), width="large"),
            },
            key="folder_candidate_editor",
        )
        selected_paths = [str(row["path"]) for _, row in edited.iterrows() if bool(row.get("select"))]
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = selected_paths
        return selected_paths

    selected = st.multiselect(
        t("home.candidates.table.select"),
        [str(row["path"]) for row in rows],
        default=[path for path in selected_paths if path in {str(row["path"]) for row in rows}],
    )
    st.dataframe(rows, use_container_width=True)
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
    st.dataframe(operation_result.get("results") or [], use_container_width=True)


def _render_process_steps() -> None:
    st.markdown(f"**{t('home.process_title')}**")
    for column, key in zip(st.columns(4, gap="medium"), ("step1", "step2", "step3", "step4"), strict=False):
        with column:
            card_open("workflow-step-card")
            st.markdown(
                f"""
                <div class="card-title">{safe_display_text(t(f"home.process.{key}_title"))}</div>
                <div class="card-muted">{safe_display_text(t(f"home.process.{key}_desc"))}</div>
                """,
                unsafe_allow_html=True,
            )
            card_close()


def render_home(context: UIContext) -> None:
    card_open("hero-card")
    st.markdown(
        f"""
        <div class="hero-row">
          <div>
            <div class="hero-title">{safe_display_text(t('home.hero.title'))}</div>
            <div class="hero-subtitle">{safe_display_text(t('home.hero.subtitle'))}</div>
          </div>
          <span class="version-badge">v{safe_display_text(__version__)}</span>
        </div>
        <div class="feature-chips">
          <span class="feature-chip">{safe_display_text(t('home.hero.chip_scan'))}</span>
          <span class="feature-chip">{safe_display_text(t('home.hero.chip_preview'))}</span>
          <span class="feature-chip">{safe_display_text(t('home.hero.chip_quarantine'))}</span>
          <span class="feature-chip">{safe_display_text(t('home.hero.chip_report'))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    card_close()

    st.info(t("home.safety_notice"))
    _render_process_steps()

    scan_options_obj = st.session_state.get(SESSION_FOLDER_SCAN_OPTIONS)
    scan_options = cast(dict[str, object], scan_options_obj) if isinstance(scan_options_obj, dict) else {}
    stale_days = safe_int(scan_options.get("stale_days", 365))
    recursive = bool(scan_options.get("recursive", True))
    max_files = safe_int(scan_options.get("max_files", 5000))
    large_file_bytes = safe_int(scan_options.get("large_file_bytes", 250 * 1024 * 1024))

    col_main, col_side = st.columns([2, 1], gap="large")
    with col_main:
        card_open("primary-action-card")
        st.markdown(f'<div class="card-title">{safe_display_text(t("home.scan.title"))}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="card-muted">{safe_display_text(t("home.scan.description"))}</div>',
            unsafe_allow_html=True,
        )
        folder_path = st.text_input(
            t("home.scan.input_label"),
            value=str(st.session_state.get(SESSION_FOLDER_SCAN_PATH) or ""),
            placeholder=t("home.scan.input_placeholder"),
            key=SESSION_FOLDER_SCAN_PATH,
        )

        if st.button(t("home.scan.button"), type="primary", key="scan_folder_button"):
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

        scan = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_SCAN_CURRENT))
        if scan:
            stats_obj = scan.get("stats")
            stats = cast(dict[str, object], stats_obj) if isinstance(stats_obj, dict) else {}
            current_quarantine_items, scan_quarantine_warnings = get_quarantine_items_safe(str(scan.get("path") or ""))
            records = [item for item in cast(list[object], scan.get("records") or []) if isinstance(item, dict)]
            candidates = [item for item in records if item.get("candidate_reasons")]

            metric_cols = st.columns(6)
            metrics = [
                (stats.get("scanned_files", 0), t("home.metrics.scanned_files")),
                (len(candidates), t("home.metrics.candidates")),
                (human_bytes(safe_int(stats.get("total_bytes"))), t("home.metrics.total_size")),
                (stats.get("stale_candidates", 0), t("home.metrics.stale_candidates")),
                (stats.get("large_candidates", 0), t("home.metrics.large_candidates")),
                (len(current_quarantine_items), t("home.metrics.quarantined")),
            ]
            for column, (value, label) in zip(metric_cols, metrics, strict=False):
                with column:
                    card_open("status-card")
                    render_safe_html_text("status-metric", value, max_chars=200)
                    render_safe_html_text("status-label", label, max_chars=200)
                    card_close()

            errors = _coerce_message_list(scan.get("errors"))
            if scan_quarantine_warnings:
                errors.extend(scan_quarantine_warnings)
            if errors:
                with st.expander(t("home.scan.warnings"), expanded=False):
                    for message in errors[:50]:
                        st.write(f"- {safe_display_text(message)}")

            st.markdown(f"**{t('home.summary.title')}**")
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
            st.write(
                f"- {t('home.summary.scanned_files', count=stats.get('scanned_files', 0))}\n"
                f"- {t('home.summary.candidate_files', count=len(candidates))}\n"
                f"- {t('home.summary.reviewable_space', size=human_bytes(sum(safe_int(item.get('size_bytes')) for item in candidates)))}\n"
                f"- {t('home.summary.quarantined_this_session', count=operation_summary_obj.get('success', 0))}\n"
                f"- {t('home.summary.restored_this_session', count=restored_summary_obj.get('success', 0))}"
            )

            st.subheader(t("home.candidates.title"))
            selected_paths = _render_candidate_editor(context, candidates)
            confirm_quarantine = st.checkbox(
                t("home.candidates.confirm_quarantine"),
                value=False,
                key="confirm_quarantine_move",
            )
            action_col1, action_col2 = st.columns(2)
            with action_col1:
                if st.button(t("home.candidates.preview_button"), key="preview_folder_action", disabled=not selected_paths):
                    st.session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] = preview_selected_actions(scan, selected_paths)
            with action_col2:
                if st.button(
                    t("home.candidates.quarantine_button"),
                    key="run_folder_action",
                    disabled=(not selected_paths or not confirm_quarantine),
                ):
                    operation_result, refreshed_scan, report_snapshot = quarantine_selected_files(
                        scan,
                        selected_paths,
                        recursive=recursive,
                        max_files=max_files,
                        stale_days=stale_days,
                        large_file_bytes=large_file_bytes,
                    )
                    st.session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] = operation_result
                    st.session_state[SESSION_FOLDER_REPORT_SNAPSHOT] = report_snapshot
                    st.session_state[SESSION_FOLDER_SCAN_CURRENT] = refreshed_scan

            st.subheader(t("home.operation_results.title"))
            _render_operation_results(st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT))

            export_scan, export_operation = resolve_report_inputs(
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_SCAN_CURRENT) or {}),
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_REPORT_SNAPSHOT) or {}),
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT) or {}),
            )

            report_payload = export_folder_report_markdown(export_scan, export_operation)
            with st.expander(t("home.report.preview_title"), expanded=True):
                st.code(report_payload[:4000], language="markdown")
            st.download_button(
                t("home.report.export_md"),
                report_payload,
                file_name="smart-organizer-report.md",
                mime="text/markdown",
            )
            st.download_button(
                t("home.report.export_csv"),
                export_folder_report_csv(export_scan, export_operation),
                file_name="smart-organizer-report.csv",
                mime="text/csv",
            )

            st.subheader(t("home.dashboard.title"))
            top_largest = sorted(records, key=lambda item: int(item.get("size_bytes") or 0), reverse=True)[:10]
            top_stale = sorted(
                [item for item in records if item.get("is_stale")],
                key=lambda item: int(item.get("days_since_access") or 0),
                reverse=True,
            )[:10]
            dash_col1, dash_col2 = st.columns(2)
            with dash_col1:
                st.markdown(f"**{t('home.dashboard.top_largest')}**")
                if top_largest:
                    for item in top_largest:
                        st.write(f"- {safe_display_text(item.get('name'))} | {human_bytes(int(item.get('size_bytes') or 0))}")
                else:
                    st.info(t("home.dashboard.empty_largest"))
            with dash_col2:
                st.markdown(f"**{t('home.dashboard.top_stale')}**")
                if top_stale:
                    for item in top_stale:
                        st.write(
                            f"- {safe_display_text(item.get('name'))} | "
                            f"{t('home.dashboard.days_idle', days=safe_display_text(item.get('days_since_access')))}"
                        )
                else:
                    st.info(t("home.dashboard.empty_stale"))

            recommendation_summary = summarize_recommendations(records, candidates)
            st.markdown(f"**{t('home.recommended_actions.title')}**")
            st.write(
                f"- {recommendation_display_label(Recommendation.SAFE_TO_REVIEW.value)}: {recommendation_summary[Recommendation.SAFE_TO_REVIEW.value]}\n"
                f"- {recommendation_display_label(Recommendation.NEEDS_MANUAL_CHECK.value)}: {recommendation_summary[Recommendation.NEEDS_MANUAL_CHECK.value]}\n"
                f"- {recommendation_display_label(Recommendation.DO_NOT_TOUCH.value)}: {recommendation_summary[Recommendation.DO_NOT_TOUCH.value]}"
            )
        else:
            st.info(t("home.scan.empty"))
        card_close()

    with col_side:
        card_open("secondary-action-card")
        st.markdown(f'<div class="card-title">{safe_display_text(t("home.quarantine.title"))}</div>', unsafe_allow_html=True)
        st.markdown(
            f'<div class="card-muted">{safe_display_text(t("home.quarantine.description"))}</div>',
            unsafe_allow_html=True,
        )
        current_scan = cast(dict[str, object], st.session_state.get(SESSION_FOLDER_SCAN_CURRENT) or {})
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
            if st.button(t("home.quarantine.restore_button"), disabled=not restore_choices, key="restore_quarantine_button"):
                restore_result, restored_scan = restore_quarantine_selection(
                    str(current_scan.get("path") or folder_path),
                    [str(value) for value in restore_choices],
                    recursive=recursive,
                    max_files=max_files,
                    stale_days=stale_days,
                    large_file_bytes=large_file_bytes,
                )
                st.session_state[SESSION_FOLDER_RESTORE_RESULT] = restore_result
                if restored_scan is not None:
                    st.session_state[SESSION_FOLDER_SCAN_CURRENT] = restored_scan
            _render_operation_results(st.session_state.get(SESSION_FOLDER_RESTORE_RESULT))
        else:
            st.info(t("home.quarantine.empty"))
        card_close()

    st.caption(f"{APP_NAME} v{__version__}")
