from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from version import APP_NAME, APP_TITLE, __version__
from ui_renderers import render_dependency_status
from ui_common import UIContext, card_close, card_open, handle_ui_exception, human_bytes, is_debug, scan_local_folder

DEPENDENCY_STATUS_SESSION_KEY = "dependency_status"


def _coerce_message_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _coerce_record_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _coerce_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


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
    st.sidebar.header("設定")

    with st.sidebar.expander("主流程：資料夾掃描", expanded=True):
        folder_dry_run = st.checkbox("Dry-run（只預覽不搬動）", value=True, key="folder_dry_run")
        stale_days = st.slider("多久算久未使用", 7, 3650, 364, step=7)
        recursive = st.checkbox("遞迴掃描子資料夾", value=True, key="folder_recursive")
        max_files = st.number_input("最大掃描檔案數", min_value=100, max_value=200000, value=5000, step=500)
        st.session_state.folder_scan_options = {
            "dry_run": bool(folder_dry_run),
            "stale_days": int(stale_days),
            "recursive": bool(recursive),
            "max_files": int(max_files),
        }

    with st.sidebar.expander("輔助：上傳單檔分析", expanded=False):
        upload_hard_limit_mb = int(context.max_upload_bytes / (1024 * 1024))
        st.caption(f"單檔上傳上限：{upload_hard_limit_mb} MB")
        st.caption("適合先驗證分類結果，再進行整批整理。")

    with st.sidebar.expander("進階設定：PDF / OCR / AI / 除錯", expanded=False):
        debug_mode = st.checkbox("Debug 模式", value=False, key="debug_mode_checkbox")
        st.session_state.debug_mode = bool(debug_mode)
        if is_debug() and st.session_state.get("current_processing_file"):
            st.caption(f"目前處理：{st.session_state.current_processing_file}")

        ai_enabled = st.toggle("啟用 AI 摘要", value=False, key="ai_enabled_toggle")
        enable_pdf_preview = st.checkbox("啟用 PDF 預覽", value=False, key="enable_pdf_preview")
        enable_ocr = st.checkbox("啟用 OCR", value=False, key="enable_ocr")
        max_heavy_mb = st.slider("耗時處理檔案上限 (MB)", 1, 200, 15, key="max_heavy_mb")
        pdf_text_max_pages = st.slider("PDF 文字抽取頁數", 1, 50, 3, key="pdf_text_max_pages")
        pdf_ocr_max_pages = st.slider(
            "PDF OCR 頁數",
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

        st.divider()
        st.markdown("**清理 uploads 內孤兒檔案**")
        cleanup_dry_run = st.checkbox("Dry-run", value=True, key="cleanup_dry_run")

        if st.button("掃描孤兒檔案", key="scan_orphans"):
            try:
                actions = context.storage.cleanup_orphaned_uploads(dry_run=True)
                st.session_state.cleanup_actions = actions
                st.success(f"找到 {len(actions)} 筆可清理項目")
            except Exception as exc:
                st.error(f"掃描失敗：{exc}")

        if st.button("實際清理", key="do_cleanup", disabled=cleanup_dry_run):
            try:
                actions = context.storage.cleanup_orphaned_uploads(dry_run=False)
                st.session_state.cleanup_actions = actions
                st.success(f"已清理 {len(actions)} 筆項目")
            except Exception as exc:
                st.error(f"清理失敗：{exc}")

        actions = st.session_state.get("cleanup_actions") or []
        if actions and st.checkbox("顯示清理明細", value=False, key="show_cleanup_actions"):
            for action in actions[:50]:
                st.write(f"- {action.get('type')}: {action.get('path')}")

    with st.sidebar.expander("環境與依賴檢查", expanded=False):
        dependency_status = get_cached_dependency_status(st.session_state)
        check_clicked = st.button("Check dependencies", key="check_dependencies_button")
        refresh_clicked = dependency_status is not None and st.button(
            "Refresh dependency check",
            key="refresh_dependencies_button",
        )

        if check_clicked or refresh_clicked:
            dependency_status = refresh_dependency_status(context)
            st.success("Dependency check completed.")

        if dependency_status is None:
            st.caption("尚未檢查")
        else:
            render_dependency_status(dependency_status)
        if is_debug():
            st.caption("processing_options")
            st.json(st.session_state.get("processing_options") or {})

    st.sidebar.markdown(
        f"**專案路徑**\n"
        f"- 根目錄：`{context.project_root}`\n"
        f"- uploads：`{context.upload_dir}`\n"
        f"- repo：`{context.repo_root}`\n"
        f"- database：`{context.db_path}`"
    )


def render_home(context: UIContext) -> None:
    card_open("hero-card")
    st.markdown(
        f"""
        <div class="hero-title">
          {APP_TITLE} <span class="version-badge">v{__version__}</span>
        </div>
        <div class="hero-subtitle">
          先掃描資料夾與久未使用檔案，再透過上傳分析、預覽確認與執行整理完成整個流程。
        </div>
        <div class="feature-chips">
          <span class="feature-chip">資料夾掃描</span>
          <span class="feature-chip">上傳分析</span>
          <span class="feature-chip">預覽確認</span>
          <span class="feature-chip">Dry-run 安全模式</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    card_close()

    scan_options = dict(st.session_state.get("folder_scan_options") or {})
    dry_run = bool(scan_options.get("dry_run", True))
    stale_days = int(scan_options.get("stale_days", 364))
    recursive = bool(scan_options.get("recursive", True))
    max_files = int(scan_options.get("max_files", 5000))

    col_main, col_side = st.columns([2, 1], gap="large")
    with col_main:
        card_open("primary-action-card")
        st.markdown('<div class="card-title">資料夾掃描總覽</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="card-muted">快速盤點檔案大小、最後修改時間與久未使用候選，先看結果再決定是否整理。</div>',
            unsafe_allow_html=True,
        )
        folder_path = st.text_input(
            "掃描資料夾路徑",
            value=str(st.session_state.get("folder_scan_path") or ""),
            placeholder=r"C:\Users\you\Downloads",
            key="folder_scan_path",
        )
        st.caption(f"Dry-run：{'開啟' if dry_run else '關閉'}")

        if st.button("開始掃描", type="primary", key="scan_folder_button"):
            normalized = str(folder_path or "").strip().strip('"')
            if not normalized:
                st.error("請先輸入資料夾路徑。")
            else:
                try:
                    path_obj = Path(normalized).expanduser()
                    if not path_obj.exists():
                        st.error("找不到指定資料夾。")
                    elif not path_obj.is_dir():
                        st.error("輸入路徑不是資料夾。")
                    else:
                        with st.spinner("掃描中..."):
                            st.session_state.folder_scan = scan_local_folder(
                                str(path_obj),
                                recursive=recursive,
                                max_files=max_files,
                                stale_days=stale_days,
                            )
                        scan = st.session_state.folder_scan
                        st.success(
                            f"掃描完成：{scan.get('stats', {}).get('scanned_files', 0)} 個檔案，"
                            f"耗時 {scan.get('elapsed_seconds', 0)} 秒"
                        )
                except PermissionError:
                    st.error("沒有權限讀取此資料夾。")
                except Exception as exc:
                    handle_ui_exception("資料夾掃描失敗。", exc)

        scan = st.session_state.get("folder_scan")
        if isinstance(scan, dict):
            stats = dict(scan.get("stats") or {})
            errors = _coerce_message_list(scan.get("errors"))
            records = _coerce_record_list(scan.get("records"))
            st.divider()
            st.write(
                f"- 路徑：`{scan.get('path')}`\n"
                f"- 遞迴：{'是' if scan.get('recursive') else '否'}\n"
                f"- 檔案數：{stats.get('scanned_files', 0)}\n"
                f"- 總大小：{human_bytes(int(stats.get('total_bytes') or 0))}\n"
                f"- 久未使用：{stats.get('stale_candidates', 0)}（{scan.get('stale_days', 0)} 天）"
            )
            if errors:
                with st.expander("掃描錯誤", expanded=False):
                    for message in errors[:50]:
                        st.write(f"- {message}")

            with st.expander("候選清單", expanded=True):
                if not records:
                    st.info("沒有可顯示的檔案。")
                else:
                    stale = [item for item in records if item.get("is_stale")]
                    largest = sorted(records, key=lambda item: _coerce_int(item.get("size_bytes")), reverse=True)[:20]
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("**久未使用前 20 筆**")
                        for item in stale[:20]:
                            st.write(
                                f"- `{item.get('name')}` | {human_bytes(_coerce_int(item.get('size_bytes')))} | {str(item.get('mtime') or '')[:10]}"
                            )
                    with col_b:
                        st.markdown("**最大檔案前 20 筆**")
                        for item in largest:
                            st.write(f"- `{item.get('name')}` | {human_bytes(_coerce_int(item.get('size_bytes')))}")
        else:
            st.info("輸入本機資料夾後即可先做盤點。")
        card_close()

    with col_side:
        card_open("secondary-action-card")
        st.markdown('<div class="card-title">快速單檔驗證</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="card-muted">先上傳一個檔案試跑分類與預覽，再決定是否做整批整理。</div>',
            unsafe_allow_html=True,
        )
        uploaded = st.file_uploader(
            "選擇單一檔案",
            type=["pdf", "jpg", "jpeg", "png", "mp4", "mov", "mkv"],
            accept_multiple_files=False,
            key="single_file_uploader",
        )
        if uploaded is not None:
            st.info("切換到「上傳分析」頁即可正式分析。")
        card_close()

    scan = st.session_state.get("folder_scan") or {}
    stats = dict(scan.get("stats") or {}) if isinstance(scan, dict) else {}
    metrics = [
        (int(stats.get("scanned_files") or 0), "已掃描檔案"),
        (int(stats.get("stale_candidates") or 0), "久未使用候選"),
        (int(len(st.session_state.get("analysis_results") or [])), "待確認分析結果"),
        (int(len(st.session_state.get("execution_results") or [])), "已完成整理"),
    ]
    columns = st.columns(4, gap="large")
    for column, (value, label) in zip(columns, metrics):
        with column:
            card_open("status-card")
            st.markdown(f'<div class="status-metric">{value}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="status-label">{label}</div>', unsafe_allow_html=True)
            card_close()

    st.divider()
    st.caption(f"{APP_NAME} v{__version__}")
