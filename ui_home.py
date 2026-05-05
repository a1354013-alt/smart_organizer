from __future__ import annotations

from pathlib import Path
from typing import cast

import streamlit as st

from folder_models import human_bytes, safe_int
from folder_organizer import (
    list_quarantine_items,
    restore_quarantined_items,
    run_folder_organizer,
    scan_local_folder,
)
from folder_report import export_folder_report_csv, export_folder_report_markdown
from ui_common import (
    UIContext,
    card_close,
    card_open,
    handle_ui_exception,
    is_debug,
)
from ui_renderers import render_dependency_status
from version import APP_NAME, APP_TITLE, __version__


def render_sidebar(context: UIContext) -> None:
    st.sidebar.header("Folder organizer settings")

    with st.sidebar.expander("Scan options", expanded=True):
        folder_dry_run = st.checkbox("Default to dry-run preview", value=True, key="folder_dry_run")
        stale_days = st.slider("Consider unused after this many days", 7, 3650, 365, step=7)
        large_file_mb = st.slider("Large file threshold (MB)", 10, 2048, 250, step=10)
        recursive = st.checkbox("Scan subfolders", value=True, key="folder_recursive")
        max_files = st.number_input("Max files to inspect", min_value=100, max_value=200000, value=5000, step=500)
        st.session_state.folder_scan_options = {
            "dry_run": bool(folder_dry_run),
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
        st.session_state.debug_mode = bool(debug_mode)
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

        st.session_state.ai_enabled = bool(ai_enabled)
        st.session_state.processing_options = {
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
        render_dependency_status(context.processor.get_dependency_status())
        if is_debug():
            st.caption("processing_options")
            st.json(st.session_state.get("processing_options") or {})

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
        return []

    rows = []
    for item in candidates:
        rows.append(
            {
                "select": False,
                "name": item.get("name"),
                "size": human_bytes(int(cast(int, item.get("size_bytes") or 0))),
                "last_modified": str(item.get("mtime") or "")[:19],
                "days_since_access": item.get("days_since_access"),
                "reasons": ", ".join(str(reason) for reason in cast(list[object], item.get("candidate_reasons") or [])),
                "recommendation": item.get("recommendation"),
                "path": item.get("path"),
            }
        )

    if context.pandas is not None:
        df = context.pandas.DataFrame(rows)
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
        return [str(row["path"]) for _, row in edited.iterrows() if bool(row.get("select"))]

    selected = st.multiselect("Select files to move to quarantine", [str(row["path"]) for row in rows])
    st.dataframe(rows, use_container_width=True)
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

    scan_options_obj = st.session_state.get("folder_scan_options")
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
            value=str(st.session_state.get("folder_scan_path") or ""),
            placeholder=r"C:\Users\you\Downloads",
            key="folder_scan_path",
        )

        if st.button("Scan folder", type="primary", key="scan_folder_button"):
            normalized = str(folder_path or "").strip().strip('"')
            if not normalized:
                st.error("Enter a folder path first.")
            else:
                try:
                    path_obj = Path(normalized).expanduser()
                    if not path_obj.exists():
                        st.error("The folder does not exist.")
                    elif not path_obj.is_dir():
                        st.error("The path must point to a folder.")
                    else:
                        progress_bar = st.progress(0)
                        status_text = st.empty()

                        def on_progress(scanned: int, cap: int) -> None:
                            progress_bar.progress(min(1.0, scanned / max(1, cap)))
                            status_text.text(f"Scanning... {scanned} files inspected")

                        st.session_state.folder_scan = scan_local_folder(
                            str(path_obj),
                            recursive=recursive,
                            max_files=max_files,
                            stale_days=stale_days,
                            large_file_bytes=large_file_bytes,
                            progress_callback=on_progress,
                        )
                        progress_bar.progress(1.0)
                        status_text.text("Scan complete.")
                        st.session_state.folder_operation_result = None
                        st.session_state.folder_restore_result = None
                except PermissionError:
                    st.error("Permission denied while scanning this folder.")
                except Exception as exc:
                    handle_ui_exception("Folder scan failed.", exc)

        scan = st.session_state.get("folder_scan")
        if scan:
            stats_obj = scan.get("stats")
            stats = cast(dict[str, object], stats_obj) if isinstance(stats_obj, dict) else {}
            quarantine_items = list_quarantine_items(str(scan.get("path") or ""))

            metric_cols = st.columns(5)
            metrics = [
                (stats.get("scanned_files", 0), "Scanned files"),
                (human_bytes(safe_int(stats.get("total_bytes"))), "Total size"),
                (stats.get("stale_candidates", 0), "Stale candidates"),
                (stats.get("large_candidates", 0), "Large file candidates"),
                (len(quarantine_items), "Quarantine items"),
            ]
            for column, (value, label) in zip(metric_cols, metrics):
                with column:
                    card_open("status-card")
                    st.markdown(f'<div class="status-metric">{value}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="status-label">{label}</div>', unsafe_allow_html=True)
                    card_close()

            if scan.get("errors"):
                with st.expander("Scan warnings", expanded=False):
                    for message in list(scan.get("errors") or [])[:50]:
                        st.write(f"- {message}")

            records = list(scan.get("records") or [])
            candidates = [item for item in records if item.get("candidate_reasons")]

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
                    st.session_state.folder_operation_result = run_folder_organizer(scan, selected_paths, dry_run=True)
            with action_col2:
                if st.button(
                    "Move selected files to quarantine",
                    key="run_folder_action",
                    disabled=(not selected_paths or not confirm_quarantine),
                ):
                    st.session_state.folder_operation_result = run_folder_organizer(scan, selected_paths, dry_run=False)
                    st.session_state.folder_scan = scan_local_folder(
                        str(scan.get("path")),
                        recursive=recursive,
                        max_files=max_files,
                        stale_days=stale_days,
                        large_file_bytes=large_file_bytes,
                    )

            st.subheader("Operation results")
            _render_operation_results(st.session_state.get("folder_operation_result"))

            report_payload = export_folder_report_markdown(
                st.session_state.get("folder_scan") or scan,
                st.session_state.get("folder_operation_result"),
            )
            st.download_button(
                "Export Markdown report",
                report_payload,
                file_name="smart-organizer-report.md",
                mime="text/markdown",
            )
            st.download_button(
                "Export CSV report",
                export_folder_report_csv(
                    st.session_state.get("folder_scan") or scan,
                    st.session_state.get("folder_operation_result"),
                ),
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
                    st.write(f"- `{item.get('name')}` | {human_bytes(int(item.get('size_bytes') or 0))}")
            with dash_col2:
                st.markdown("**Top stale files**")
                for item in top_stale:
                    st.write(f"- `{item.get('name')}` | {item.get('days_since_access')} days idle")

            safe_archive = sum(1 for item in candidates if item.get("recommendation") == "Safe to archive")
            manual_review = sum(1 for item in candidates if item.get("recommendation") == "Needs manual review")
            avoid_auto = sum(1 for item in records if item.get("recommendation") == "Not recommended for automatic handling")
            st.markdown("**Recommended actions**")
            st.write(
                f"- Safe to archive: {safe_archive}\n"
                f"- Needs manual review: {manual_review}\n"
                f"- Not recommended for automatic handling: {avoid_auto}"
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
        current_scan = st.session_state.get("folder_scan") or {}
        quarantine_items = list_quarantine_items(str(current_scan.get("path") or folder_path or "")) if (current_scan or folder_path) else []
        if quarantine_items:
            restore_choices = st.multiselect(
                "Choose quarantine items to restore",
                options=[item["quarantine_path"] for item in quarantine_items],
                format_func=lambda value: Path(value).name,
                key="quarantine_restore_paths",
            )
            if st.button("Restore selected quarantine items", disabled=not restore_choices, key="restore_quarantine_button"):
                st.session_state.folder_restore_result = restore_quarantined_items(
                    str(current_scan.get("path") or folder_path),
                    [str(value) for value in restore_choices],
                )
                if current_scan:
                    st.session_state.folder_scan = scan_local_folder(
                        str(current_scan.get("path")),
                        recursive=recursive,
                        max_files=max_files,
                        stale_days=stale_days,
                        large_file_bytes=large_file_bytes,
                    )
            _render_operation_results(st.session_state.get("folder_restore_result"))
        else:
            st.info("No active quarantine items for the current folder.")
        card_close()

    st.divider()
    st.caption(f"{APP_NAME} v{__version__}")
