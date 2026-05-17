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
from ui_common import (
    UIContext,
    card_close,
    card_open,
    handle_ui_exception,
    is_debug,
    render_safe_html_text,
    safe_display_text,
)
from ui_labels import recommendation_display_label
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
from version import APP_NAME, APP_TITLE, __version__

DEPENDENCY_STATUS_SESSION_KEY = "dependency_status"


def _coerce_message_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


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
    st.sidebar.header("Smart Organizer")
    st.sidebar.markdown(
        "**Main workflow**\n"
        "- Local folder organization\n"
        "- Long-unused file review\n"
        "- Safe quarantine and restore\n\n"
        "**Advanced workflow**\n"
        "- Upload file analysis\n"
        "- Classification, search, and records"
    )
    st.sidebar.caption(
        "Async batch processing is currently an internal/future-use path; the UI uses the safer synchronous flow for clearer progress and errors."
    )

    with st.sidebar.expander("Scan options", expanded=True):
        stale_days = st.slider("Consider unused after this many days", 7, 3650, 365, step=7)
        large_file_mb = st.slider("Large file threshold (MB)", 10, 2048, 250, step=10)
        recursive = st.checkbox("Scan subfolders", value=True, key="folder_recursive")
        max_files = st.number_input("Max files to inspect", min_value=100, max_value=200000, value=5000, step=500)
        st.session_state[SESSION_FOLDER_SCAN_OPTIONS] = {
            "stale_days": int(stale_days),
            "large_file_bytes": int(large_file_mb) * 1024 * 1024,
            "recursive": bool(recursive),
            "max_files": int(max_files),
        }

    with st.sidebar.expander("Upload analysis options", expanded=False):
        upload_hard_limit_mb = int(context.max_upload_bytes / (1024 * 1024))
        st.caption(f"Maximum upload size: {upload_hard_limit_mb} MB")
        st.caption("These options affect the Upload / Review flow, not the folder organizer scan.")

    with st.sidebar.expander("PDF / OCR / AI / diagnostics", expanded=False):
        debug_mode = st.checkbox("Debug mode", value=False, key="debug_mode_checkbox")
        st.session_state[SESSION_DEBUG_MODE] = bool(debug_mode)
        if is_debug() and st.session_state.get("current_processing_file"):
            st.caption(f"Current processing file: {st.session_state.current_processing_file}")

        ai_enabled = st.toggle("Enable AI summary", value=False, key="ai_enabled_toggle")
        enable_pdf_preview = st.checkbox("Enable PDF preview", value=False, key="enable_pdf_preview")
        enable_ocr = st.checkbox("Enable OCR", value=False, key="enable_ocr")
        max_heavy_mb = st.slider("Heavy file threshold (MB)", 1, 200, 15, key="max_heavy_mb")
        pdf_text_max_pages = st.slider("PDF text extraction pages", 1, 50, 3, key="pdf_text_max_pages")
        pdf_ocr_max_pages = st.slider(
            "PDF OCR pages",
            1,
            5,
            max(1, min(5, int(getattr(context.processor, "pdf_ocr_max_pages", 3)))),
            key="pdf_ocr_max_pages",
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

    with st.sidebar.expander("Dependencies", expanded=False):
        dependency_status = get_cached_dependency_status(st.session_state)
        if st.button("Check dependencies", key="check_dependencies_button"):
            dependency_status = refresh_dependency_status(context)
            st.success("Dependency check completed.")
        elif dependency_status is None:
            st.caption("Run a dependency check to inspect optional runtime tools.")

        if dependency_status is not None:
            render_dependency_status(dependency_status)

        if is_debug():
            st.caption("processing_options")
            st.json(st.session_state.get(SESSION_PROCESSING_OPTIONS) or {})

    st.sidebar.markdown(
        f"**Workspace**\n"
        f"- project root: `{context.project_root}`\n"
        f"- uploads: `{context.upload_dir}`\n"
        f"- repo: `{context.repo_root}`\n"
        f"- database: `{context.db_path}`"
    )


def _render_candidate_editor(context: UIContext, candidates: list[dict[str, object]]) -> list[str]:
    if not candidates:
        st.info("No stale or large-file candidates were found in this scan.")
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = []
        return []

    st.caption(f"Risk labels: {' | '.join(RISK_LABELS)}")
    if st.button("Select all candidates for preview", key="select_all_candidates_for_preview"):
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = [str(item.get("path")) for item in candidates]
    if st.button("Select all safe-to-review candidates", key="select_safe_review_candidates"):
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = [
            str(item.get("path")) for item in candidates if item.get("risk_level") == "safe_to_review"
        ]
    if st.button("Clear candidate selection", key="clear_candidate_selection"):
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = []

    rows = []
    for item in candidates:
        rows.append(
            {
                "select": False,
                "name": item.get("name"),
                "size": human_bytes(int(cast(int, item.get("size_bytes") or 0))),
                "last_modified": str(item.get("mtime") or "")[:19],
                "days_since_access": item.get("days_since_access"),
                "confidence": item.get("confidence"),
                "risk_level": item.get("risk_level"),
                "reasons": ", ".join(str(reason) for reason in cast(list[object], item.get("candidate_reasons") or [])),
                "recommendation": recommendation_display_label(item.get("recommendation")),
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
                "select": st.column_config.CheckboxColumn("Select"),
                "path": st.column_config.TextColumn("Path", width="large"),
            },
            key="folder_candidate_editor",
        )
        selected_paths = [str(row["path"]) for _, row in edited.iterrows() if bool(row.get("select"))]
        st.session_state[SESSION_FOLDER_SELECTED_PATHS] = selected_paths
        return selected_paths

    selected = st.multiselect(
        "Select files to move to quarantine",
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
        f"- Selected: {summary.get('selected', 0)}\n"
        f"- Success: {summary.get('success', 0)}\n"
        f"- Failed: {summary.get('failed', 0)}\n"
        f"- Skipped: {summary.get('skipped', 0)}"
    )
    st.dataframe(operation_result.get("results") or [], use_container_width=True)


def render_home(context: UIContext) -> None:
    card_open("hero-card")
    st.markdown(
        f"""
        <div class="hero-title">
          {APP_TITLE} <span class="version-badge">v{__version__}</span>
        </div>
        <div class="hero-subtitle">
          A safe folder-cleanup assistant for portfolio demos: scan a folder, find stale or large files,
          preview what would happen, move selected items into quarantine, and restore them later if needed.
        </div>
        <div class="feature-chips">
          <span class="feature-chip">Folder scan first</span>
          <span class="feature-chip">Dry-run preview</span>
          <span class="feature-chip">Quarantine, not delete</span>
          <span class="feature-chip">Report export</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    card_close()

    st.markdown("**Workflow:** Scan -> Preview -> Quarantine -> Restore -> Export report")
    st.info(
        "Safety guardrails: selected user files are not directly deleted, every cleanup move goes to quarantine first, "
        "restore is available, and atime/mtime are only supporting signals. Internal temp files and previews may still be cleaned up by maintenance tools."
    )

    scan_options_obj = st.session_state.get(SESSION_FOLDER_SCAN_OPTIONS)
    scan_options = cast(dict[str, object], scan_options_obj) if isinstance(scan_options_obj, dict) else {}
    stale_days = safe_int(scan_options.get("stale_days", 365))
    recursive = bool(scan_options.get("recursive", True))
    max_files = safe_int(scan_options.get("max_files", 5000))
    large_file_bytes = safe_int(scan_options.get("large_file_bytes", 250 * 1024 * 1024))

    col_main, col_side = st.columns([2, 1], gap="large")
    with col_main:
        card_open("primary-action-card")
        st.markdown('<div class="card-title">Scan a folder safely</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="card-muted">The organizer scans metadata only on this page. It does not delete anything and it never moves files automatically.</div>',
            unsafe_allow_html=True,
        )
        folder_path = st.text_input(
            "Folder to scan",
            value=str(st.session_state.get(SESSION_FOLDER_SCAN_PATH) or ""),
            placeholder=r"C:\Users\you\Downloads",
            key=SESSION_FOLDER_SCAN_PATH,
        )

        if st.button("Scan folder", type="primary", key="scan_folder_button"):
            try:
                progress_bar = st.progress(0)
                status_text = st.empty()

                def on_progress(scanned: int, cap: int) -> None:
                    progress_bar.progress(min(1.0, scanned / max(1, cap)))
                    status_text.text(f"Scanning... {scanned} files inspected")

                st.session_state[SESSION_FOLDER_SCAN_CURRENT] = scan_folder(
                    folder_path,
                    recursive=recursive,
                    max_files=max_files,
                    stale_days=stale_days,
                    large_file_bytes=large_file_bytes,
                    progress_callback=on_progress,
                )
                progress_bar.progress(1.0)
                status_text.text("Scan complete.")
                st.session_state[SESSION_FOLDER_REPORT_SNAPSHOT] = build_report_snapshot(
                    cast(dict[str, object], st.session_state.get(SESSION_FOLDER_SCAN_CURRENT) or {})
                )
                st.session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] = None
                st.session_state[SESSION_FOLDER_RESTORE_RESULT] = None
                st.session_state[SESSION_FOLDER_SELECTED_PATHS] = []
            except ScanPathError as exc:
                st.error(str(exc))
            except PermissionError:
                st.error("Permission denied while scanning this folder.")
            except FolderOrganizerError as exc:
                st.error(str(exc))
            except Exception as exc:
                handle_ui_exception("Folder scan failed.", exc)

        scan = cast(dict[str, object] | None, st.session_state.get(SESSION_FOLDER_SCAN_CURRENT))
        if scan:
            stats_obj = scan.get("stats")
            stats = cast(dict[str, object], stats_obj) if isinstance(stats_obj, dict) else {}
            quarantine_items, scan_quarantine_warnings = get_quarantine_items_safe(str(scan.get("path") or ""))
            records = [item for item in cast(list[object], scan.get("records") or []) if isinstance(item, dict)]
            candidates = [item for item in records if item.get("candidate_reasons")]

            metric_cols = st.columns(6)
            metrics = [
                (stats.get("scanned_files", 0), "Scanned files"),
                (len(candidates), "Candidates"),
                (human_bytes(safe_int(stats.get("total_bytes"))), "Total size"),
                (stats.get("stale_candidates", 0), "Stale candidates"),
                (stats.get("large_candidates", 0), "Large file candidates"),
                (len(quarantine_items), "Quarantined"),
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
                with st.expander("Scan warnings", expanded=False):
                    for message in errors[:50]:
                        st.write(f"- {safe_display_text(message)}")

            st.markdown("**Before / after summary**")
            restored_summary_obj = cast(dict[str, object], (st.session_state.get(SESSION_FOLDER_RESTORE_RESULT) or {}).get("summary", {}) if isinstance(st.session_state.get(SESSION_FOLDER_RESTORE_RESULT), dict) else {})
            operation_summary_obj = cast(dict[str, object], (st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT) or {}).get("summary", {}) if isinstance(st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT), dict) else {})
            st.write(
                f"- Scanned files: {stats.get('scanned_files', 0)}\n"
                f"- Candidate files: {len(candidates)}\n"
                f"- Estimated reviewable space: {human_bytes(sum(safe_int(item.get('size_bytes')) for item in candidates))}\n"
                f"- Quarantined this session: {operation_summary_obj.get('success', 0)}\n"
                f"- Restored this session: {restored_summary_obj.get('success', 0)}"
            )

            st.subheader("Candidate files")
            selected_paths = _render_candidate_editor(context, candidates)
            confirm_quarantine = st.checkbox(
                "I understand selected files will be moved into .smart_organizer_quarantine/ and can be restored later.",
                value=False,
                key="confirm_quarantine_move",
            )
            action_col1, action_col2 = st.columns(2)
            with action_col1:
                if st.button("Preview selected actions", key="preview_folder_action", disabled=not selected_paths):
                    st.session_state[SESSION_FOLDER_LAST_OPERATION_RESULT] = preview_selected_actions(scan, selected_paths)
            with action_col2:
                if st.button(
                    "Move selected files to quarantine",
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

            st.subheader("Operation results")
            _render_operation_results(st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT))

            export_scan, export_operation = resolve_report_inputs(
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_SCAN_CURRENT) or {}),
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_REPORT_SNAPSHOT) or {}),
                cast(dict[str, object], st.session_state.get(SESSION_FOLDER_LAST_OPERATION_RESULT) or {}),
            )

            report_payload = export_folder_report_markdown(export_scan, export_operation)
            with st.expander("Report preview", expanded=True):
                st.code(report_payload[:4000], language="markdown")
            st.download_button(
                "Export Markdown report",
                report_payload,
                file_name="smart-organizer-report.md",
                mime="text/markdown",
            )
            st.download_button(
                "Export CSV report",
                export_folder_report_csv(export_scan, export_operation),
                file_name="smart-organizer-report.csv",
                mime="text/csv",
            )

            st.subheader("Dashboard")
            top_largest = sorted(records, key=lambda item: int(item.get("size_bytes") or 0), reverse=True)[:10]
            top_stale = sorted(
                [item for item in records if item.get("is_stale")],
                key=lambda item: int(item.get("days_since_access") or 0),
                reverse=True,
            )[:10]
            dash_col1, dash_col2 = st.columns(2)
            with dash_col1:
                st.markdown("**Top largest files**")
                for item in top_largest:
                    st.write(f"- {safe_display_text(item.get('name'))} | {human_bytes(int(item.get('size_bytes') or 0))}")
            with dash_col2:
                st.markdown("**Top stale files**")
                for item in top_stale:
                    st.write(
                        f"- {safe_display_text(item.get('name'))} | "
                        f"{safe_display_text(item.get('days_since_access'))} days idle"
                    )

            recommendation_summary = summarize_recommendations(records, candidates)
            st.markdown("**Recommended actions**")
            st.write(
                f"- {recommendation_display_label(Recommendation.SAFE_TO_REVIEW.value)}: {recommendation_summary[Recommendation.SAFE_TO_REVIEW.value]}\n"
                f"- {recommendation_display_label(Recommendation.NEEDS_MANUAL_CHECK.value)}: {recommendation_summary[Recommendation.NEEDS_MANUAL_CHECK.value]}\n"
                f"- {recommendation_display_label(Recommendation.DO_NOT_TOUCH.value)}: {recommendation_summary[Recommendation.DO_NOT_TOUCH.value]}"
            )
        else:
            st.info("Scan a folder to build your cleanup candidates, quarantine list, and report.")
        card_close()

    with col_side:
        card_open("secondary-action-card")
        st.markdown('<div class="card-title">Quarantine and restore</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="card-muted">Selected files are moved into a hidden quarantine folder inside the scanned root. Nothing is permanently deleted here.</div>',
            unsafe_allow_html=True,
        )
        current_scan = cast(dict[str, object], st.session_state.get(SESSION_FOLDER_SCAN_CURRENT) or {})
        quarantine_items = []
        restore_quarantine_warnings: list[str] = []
        if current_scan or folder_path:
            quarantine_items, restore_quarantine_warnings = get_quarantine_items_safe(
                str(current_scan.get("path") or folder_path or "")
            )
        for warning in restore_quarantine_warnings:
            st.warning(safe_display_text(warning))
        if quarantine_items:
            restore_choices = st.multiselect(
                "Choose quarantine items to restore",
                options=[item["quarantine_path"] for item in quarantine_items],
                format_func=lambda value: Path(value).name,
                key="quarantine_restore_paths",
            )
            if st.button("Restore selected quarantine items", disabled=not restore_choices, key="restore_quarantine_button"):
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
            st.info("No active quarantine items for the current folder.")
        card_close()

    st.divider()
    st.caption(f"{APP_NAME} v{__version__}")
