import streamlit as st
import os
import logging
import datetime
import time
from pathlib import Path

from version import APP_NAME, APP_TITLE, __version__
from frontend_safety import inject_browser_storage_sanitizer

st.set_page_config(page_title=APP_NAME, layout="wide")
inject_browser_storage_sanitizer(enabled=True)

try:
    import pandas as pd
except Exception:
    pd = None

try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None

from core import FileProcessor, DOCUMENT_TAGS, PHOTO_TAGS, VIDEO_TAGS
from logging_config import setup_logging
from storage import MAX_UPLOAD_BYTES, StorageManager, SearchContentError
from ui_renderers import render_dependency_status, render_video_details
from services import (
    UploadedFileData,
    AnalysisResult,
    analyze_upload_batch,
    build_confirmed_results,
    finalize_batch,
    reclassify_record,
    apply_manual_topic_override,
    generate_summary_suggestion,
)

PROJECT_ROOT = Path(__file__).parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
REPO_ROOT = PROJECT_ROOT / "repo"
DB_PATH = PROJECT_ROOT / "smart_organizer.db"

setup_logging()
logger = logging.getLogger(__name__)


def _inject_global_css() -> None:
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

          /* Reduce visual pressure in sidebar */
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

          /* Give main content some breathing room */
          div[data-testid="stMainBlockContainer"] {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
          }

          /* Softer default buttons */
          .stButton > button {
            border-radius: 14px;
            border: 1px solid rgba(15, 23, 42, 0.12);
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
          }

          .stButton > button[kind="primary"] {
            background: rgba(16, 185, 129, 0.85);
            border: 1px solid rgba(16, 185, 129, 0.30);
          }

          .stButton > button[kind="primary"]:hover {
            background: rgba(16, 185, 129, 0.92);
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _card_open(class_name: str) -> None:
    st.markdown(f'<div class="{class_name}">', unsafe_allow_html=True)


def _card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def _human_bytes(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "-"
    value = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{int(num_bytes)} B"


def _is_debug() -> bool:
    return bool(st.session_state.get("debug_mode", False))


def _handle_ui_exception(user_message: str, exc: Exception) -> None:
    if _is_debug():
        st.exception(exc)
    else:
        st.error(user_message)


@st.cache_resource
def _bootstrap_services():
    processor = FileProcessor()
    storage = StorageManager(str(DB_PATH), str(REPO_ROOT), str(UPLOAD_DIR))
    return processor, storage


processor, storage = _bootstrap_services()

_inject_global_css()

_card_open("hero-card")
col_title, col_badge = st.columns([4, 1])
with col_title:
    st.markdown('<div class="hero-title">📁 智慧檔案整理助理</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="hero-subtitle">資料夾掃描、檔案分類、久未使用檔案清理</div>',
        unsafe_allow_html=True,
    )
with col_badge:
    st.markdown(f'<div class="version-badge">v{__version__}</div>', unsafe_allow_html=True)

st.markdown(
    """
    <div class="feature-chips">
      <span class="feature-chip">規則分類</span>
      <span class="feature-chip">檔案大小分析</span>
      <span class="feature-chip">久未使用檢查</span>
      <span class="feature-chip">可預覽後執行</span>
      <span class="feature-chip">Dry-run 安全模式</span>
    </div>
    """,
    unsafe_allow_html=True,
)
_card_close()


def _init_session_state():
    st.session_state.setdefault("analysis_results", [])
    st.session_state.setdefault("confirmed_results", [])
    st.session_state.setdefault("execution_results", [])
    st.session_state.setdefault("cleanup_actions", [])
    st.session_state.setdefault("review_summaries", {})
    st.session_state.setdefault("folder_scan", None)
    st.session_state.setdefault("folder_scan_actions", [])


def _reset_review_state():
    st.session_state.review_summaries = {}


def _infer_local_file_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png"}:
        return "photo"
    if ext in {".mp4", ".mov", ".mkv"}:
        return "video"
    if ext == ".pdf":
        return "document"
    if ext:
        return "document"
    return "unknown"


def _scan_local_folder(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
) -> dict[str, object]:
    started = time.perf_counter()
    root = Path(folder_path).expanduser()

    records: list[dict[str, object]] = []
    errors: list[str] = []

    now = datetime.datetime.now(datetime.timezone.utc)
    stale_delta = datetime.timedelta(days=max(0, int(stale_days)))

    scanned = 0

    def _on_walk_error(err: OSError) -> None:
        try:
            errors.append(f"掃描資料夾失敗：{err}")
        except Exception:
            return

    if recursive:
        walker = os.walk(str(root), topdown=True, onerror=_on_walk_error)
        for dirpath, _dirnames, filenames in walker:
            if scanned >= int(max_files):
                break
            for filename in filenames:
                if scanned >= int(max_files):
                    break
                p = Path(dirpath) / filename
                try:
                    stat = p.stat()
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc)
                    is_stale = (now - mtime) >= stale_delta if stale_days > 0 else False
                    records.append(
                        {
                            "path": str(p),
                            "name": p.name,
                            "ext": p.suffix.lower(),
                            "size_bytes": int(stat.st_size),
                            "mtime": mtime.isoformat(),
                            "file_kind": _infer_local_file_kind(str(p)),
                            "is_stale": bool(is_stale),
                        }
                    )
                    scanned += 1
                except PermissionError:
                    errors.append(f"權限不足：{p}")
                except FileNotFoundError:
                    continue
                except Exception as e:
                    errors.append(f"讀取失敗：{p}（{e}）")
    else:
        try:
            for entry in os.scandir(str(root)):
                if scanned >= int(max_files):
                    break
                try:
                    if not entry.is_file():
                        continue
                    stat = entry.stat()
                    p = Path(entry.path)
                    mtime = datetime.datetime.fromtimestamp(stat.st_mtime, tz=datetime.timezone.utc)
                    is_stale = (now - mtime) >= stale_delta if stale_days > 0 else False
                    records.append(
                        {
                            "path": str(p),
                            "name": p.name,
                            "ext": p.suffix.lower(),
                            "size_bytes": int(stat.st_size),
                            "mtime": mtime.isoformat(),
                            "file_kind": _infer_local_file_kind(str(p)),
                            "is_stale": bool(is_stale),
                        }
                    )
                    scanned += 1
                except PermissionError:
                    errors.append(f"權限不足：{entry.path}")
                except FileNotFoundError:
                    continue
                except Exception as e:
                    errors.append(f"讀取失敗：{entry.path}（{e}）")
        except PermissionError:
            raise
        except FileNotFoundError:
            raise
        except Exception as e:
            errors.append(f"掃描資料夾失敗：{e}")

    stats = {
        "scanned_files": len(records),
        "stale_candidates": sum(1 for r in records if r.get("is_stale")),
        "total_bytes": sum(int(r.get("size_bytes") or 0) for r in records),
        "by_kind": {
            "document": sum(1 for r in records if r.get("file_kind") == "document"),
            "photo": sum(1 for r in records if r.get("file_kind") == "photo"),
            "video": sum(1 for r in records if r.get("file_kind") == "video"),
            "unknown": sum(1 for r in records if r.get("file_kind") == "unknown"),
        },
    }

    return {
        "path": str(root),
        "recursive": bool(recursive),
        "max_files": int(max_files),
        "stale_days": int(stale_days),
        "scanned_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "records": records,
        "errors": errors[:50],
        "stats": stats,
    }


def _build_uploaded_file_batch(uploaded_files) -> list[UploadedFileData]:
    return [
        UploadedFileData(
            name=uploaded_file.name,
            content=bytes(uploaded_file.getbuffer()),
            mime_type=str(getattr(uploaded_file, "type", "") or ""),
        )
        for uploaded_file in uploaded_files
    ]


def _render_sidebar():
    st.sidebar.header("⚙️ 設定")

    with st.sidebar.expander("主流程：資料夾掃描", expanded=True):
        folder_dry_run = st.checkbox("Dry-run 安全模式（只預覽建議，不做刪除/移動）", value=True, key="folder_dry_run")
        # Avoid Streamlit widget warnings: default must align with step=7.
        stale_days = st.slider("久未使用判定（天）", 7, 3650, 364, step=7, help="以檔案最後修改時間判定。")
        recursive = st.checkbox("遞迴掃描子資料夾", value=True, key="folder_recursive")
        max_files = st.number_input("掃描上限（檔案數）", min_value=100, max_value=200000, value=5000, step=500)
        st.session_state.folder_scan_options = {
            "dry_run": bool(folder_dry_run),
            "stale_days": int(stale_days),
            "recursive": bool(recursive),
            "max_files": int(max_files),
        }

    with st.sidebar.expander("輔助：上傳單檔分析", expanded=False):
        upload_hard_limit_mb = int(MAX_UPLOAD_BYTES / (1024 * 1024))
        st.caption(f"單檔上傳硬限制：{upload_hard_limit_mb}MB（超過會拒絕上傳）")
        st.caption("用途：單檔測試/驗證分析品質；主要整理流程以『掃描資料夾』為主。")

    with st.sidebar.expander("進階設定：PDF / OCR / AI / 除錯", expanded=False):
        debug_mode = st.checkbox("Debug 模式", value=False, key="debug_mode_checkbox")
        st.session_state.debug_mode = bool(debug_mode)
        if _is_debug():
            current_file = st.session_state.get("current_processing_file")
            if current_file:
                st.caption(f"目前處理檔名：{current_file}")

        ai_enabled = st.toggle("啟用 AI 摘要（會送出內容到 OpenAI）", value=False, key="ai_enabled_toggle")
        st.caption("未啟用時，系統不會送出任何內容。")

        enable_pdf_preview = st.checkbox("啟用 PDF 預覽（需要 poppler）", value=False, key="enable_pdf_preview")
        enable_ocr = st.checkbox("啟用 OCR（需要 tesseract）", value=False, key="enable_ocr")

        max_heavy_mb = st.slider(
            "耗時處理啟用上限 (MB)",
            1,
            200,
            15,
            help="超過此大小會跳過 OCR / PDF 預覽等耗時處理，但仍可上傳與基本整理。",
            key="max_heavy_mb",
        )

        pdf_text_max_pages = st.slider("PDF 文字抽取頁數上限", 1, 50, 3, key="pdf_text_max_pages")
        pdf_ocr_max_pages = st.slider(
            "PDF OCR 頁數上限",
            1,
            5,
            max(1, min(5, int(getattr(processor, "pdf_ocr_max_pages", 3)))),
            key="pdf_ocr_max_pages",
        )

        processing_options = {
            "enable_pdf_preview": bool(enable_pdf_preview),
            "enable_ocr": bool(enable_ocr),
            "max_heavy_bytes": int(max_heavy_mb) * 1024 * 1024,
            "pdf_text_max_pages": int(pdf_text_max_pages),
            "pdf_ocr_max_pages": int(pdf_ocr_max_pages),
            "pdf_preview_max_pages": int(getattr(processor, "pdf_preview_max_pages", 1)),
            "pdf_text_timeout_seconds": 10,
            "pdf_preview_timeout_seconds": 10,
            "ocr_timeout_seconds": 15,
            "video_metadata_timeout_seconds": 10,
            "video_thumbnail_timeout_seconds": 10,
        }

        st.session_state.ai_enabled = bool(ai_enabled)
        st.session_state.processing_options = processing_options

        st.divider()
        st.markdown("**維護：uploads 清理（進階）**")
        cleanup_dry_run = st.checkbox("Dry-run（只預覽不刪除）", value=True, key="cleanup_dry_run")

        if st.button("🧹 掃描孤兒暫存檔/預覽圖", key="scan_orphans"):
            try:
                actions = storage.cleanup_orphaned_uploads(dry_run=True)
                st.session_state.cleanup_actions = actions
                st.success(f"✅ 掃描完成：{len(actions)} 個待清理項目")
            except Exception as e:
                st.error(f"❌ 掃描失敗: {e}")

        if st.button("🗑️ 執行清理", key="do_cleanup", disabled=cleanup_dry_run):
            try:
                actions = storage.cleanup_orphaned_uploads(dry_run=False)
                st.session_state.cleanup_actions = actions
                st.success(f"✅ 清理完成：{len(actions)} 個項目")
            except Exception as e:
                st.error(f"❌ 清理失敗: {e}")

        actions = st.session_state.get("cleanup_actions") or []
        if actions:
            show_actions = st.checkbox("顯示待清理清單", value=False, key="show_cleanup_actions")
            if show_actions:
                for a in actions[:50]:
                    st.write(f"- {a.get('type')}: {a.get('path')}")
                if len(actions) > 50:
                    st.caption(f"...（共 {len(actions)} 項，僅顯示前 50）")

    with st.sidebar.expander("🔍 環境與依賴檢查", expanded=False):
        deps = processor.get_dependency_status()
        render_dependency_status(deps)
        if _is_debug():
            st.caption("processing_options")
            st.json(st.session_state.get("processing_options") or {})

    st.sidebar.markdown(
        f"**系統配置**\n"
        f"- 專案根: `{PROJECT_ROOT}`\n"
        f"- 上傳目錄: `{UPLOAD_DIR}`\n"
        f"- 儲存庫: `{REPO_ROOT}`\n"
        f"- 資料庫: `{DB_PATH}`"
    )


_init_session_state()
_render_sidebar()


def _render_home_dashboard() -> None:
    _card_open("hero-card")
    st.markdown(
        f"""
        <div class="hero-title">
          🗂️ {APP_TITLE} <span class="version-badge">v{__version__}</span>
        </div>
        <div class="hero-subtitle">
          掃描資料夾、整理檔案、找出久未使用檔案，並在 <b>Dry-run</b> 安全模式下先預覽再執行。
          <br/>首頁主角是 <b>資料夾掃描</b>；PDF / OCR / AI 是進階輔助，不是主流程。
        </div>
        <div class="feature-chips">
          <span class="feature-chip">主流程：掃描資料夾</span>
          <span class="feature-chip">久未使用候選</span>
          <span class="feature-chip">Dry-run 安全模式</span>
          <span class="feature-chip">上傳單檔（輔助）</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _card_close()

    col_main, col_side = st.columns([2, 1], gap="large")
    scan_options = dict(st.session_state.get("folder_scan_options") or {})
    dry_run = bool(scan_options.get("dry_run", True))
    stale_days = int(scan_options.get("stale_days", 365))
    recursive = bool(scan_options.get("recursive", True))
    max_files = int(scan_options.get("max_files", 5000))

    with col_main:
        _card_open("primary-action-card")
        st.markdown('<div class="card-title">主流程：掃描資料夾</div>', unsafe_allow_html=True)
        st.markdown(
            """
            <div class="card-muted">
              - 只有按下「開始掃描資料夾」才會執行（不會自動掃描）<br/>
              - 先找出久未使用檔案候選（stale）與可整理方向<br/>
              - 建議先用 Dry-run 預覽，再到「執行」分頁套用動作
            </div>
            """,
            unsafe_allow_html=True,
        )

        folder_path = st.text_input(
            "輸入資料夾路徑",
            value=str(st.session_state.get("folder_scan_path") or ""),
            placeholder=r"例如：D:\Downloads 或 C:\Users\you\Desktop",
            key="folder_scan_path",
            help="Streamlit 無法直接開啟本機資料夾選擇視窗，請貼上路徑。",
        )

        st.caption(f"Dry-run 狀態：{'✅ 開啟（安全）' if dry_run else '⚠️ 關閉（請小心）'}")

        scan_clicked = st.button("🔎 掃描檔案清單", type="primary", key="scan_folder_button")
        if scan_clicked:
            normalized = str(folder_path or "").strip().strip('"')
            if not normalized:
                st.error("請先輸入資料夾路徑。")
            else:
                try:
                    path_obj = Path(normalized).expanduser()
                    if not path_obj.exists():
                        st.error("資料夾不存在，請確認路徑是否正確。")
                    elif not path_obj.is_dir():
                        st.error("指定路徑不是資料夾，請重新輸入。")
                    else:
                        with st.spinner("掃描中…（只會在按下按鈕時執行）"):
                            scan = _scan_local_folder(
                                str(path_obj),
                                recursive=recursive,
                                max_files=max_files,
                                stale_days=stale_days,
                            )
                        st.session_state.folder_scan = scan
                        st.success(
                            f"✅ 掃描完成：{scan.get('stats', {}).get('scanned_files', 0)} 個檔案"
                            f"（耗時 {scan.get('elapsed_seconds', 0)} 秒）"
                        )
                except PermissionError:
                    st.error("沒有權限讀取該資料夾，請改用其他路徑或調整權限。")
                except Exception as e:
                    logger.exception("folder scan failed")
                    _handle_ui_exception("掃描資料夾失敗，請檢查路徑與權限後重試。", e)

        scan = st.session_state.get("folder_scan")
        if scan:
            stats = dict(scan.get("stats") or {})
            st.divider()
            st.markdown("**掃描摘要**")
            st.write(
                f"- 路徑：`{scan.get('path')}`\n"
                f"- 遞迴：{('是' if scan.get('recursive') else '否')}\n"
                f"- 掃描檔案數：{stats.get('scanned_files', 0)}\n"
                f"- 總大小：{_human_bytes(int(stats.get('total_bytes') or 0))}\n"
                f"- 久未使用候選：{stats.get('stale_candidates', 0)}（{scan.get('stale_days', 0)} 天）"
            )

            if scan.get("errors"):
                with st.expander("掃描時的警告 / 權限問題", expanded=False):
                    for msg in list(scan.get("errors") or [])[:50]:
                        st.write(f"- {msg}")

            with st.expander("預覽整理建議", expanded=True):
                records = list(scan.get("records") or [])
                if not records:
                    st.info("目前沒有可用的掃描結果。")
                else:
                    stale = [r for r in records if r.get("is_stale")]
                    largest = sorted(records, key=lambda r: int(r.get("size_bytes") or 0), reverse=True)[:20]
                    oldest = sorted(records, key=lambda r: str(r.get("mtime") or ""))[:20]

                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown("**久未使用候選（前 20）**")
                        if not stale:
                            st.caption("無")
                        else:
                            for r in stale[:20]:
                                st.write(
                                    f"- `{r.get('name')}` · {_human_bytes(int(r.get('size_bytes') or 0))} · {str(r.get('mtime') or '')[:10]}"
                                )
                    with col_b:
                        st.markdown("**大型檔案（前 20）**")
                        if not largest:
                            st.caption("無")
                        else:
                            for r in largest:
                                st.write(f"- `{r.get('name')}` · {_human_bytes(int(r.get('size_bytes') or 0))}")

                    st.markdown("**提醒**：此頁面只提供掃描與建議預覽；真正的刪除/移動一定要在你確認後才會執行。")
        else:
            st.info("先掃描資料夾後，才會出現『預覽整理建議』與後續執行引導。")

        _card_close()

    with col_side:
        _card_open("secondary-action-card")
        st.markdown('<div class="card-title">輔助：上傳單檔分析</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="card-muted">用於單檔測試/驗證分析品質，不是主要整理流程。</div>',
            unsafe_allow_html=True,
        )
        uploaded = st.file_uploader(
            "選擇檔案（支援 PDF / JPG / PNG / MP4 / MOV / MKV）",
            type=["pdf", "jpg", "jpeg", "png", "mp4", "mov", "mkv"],
            accept_multiple_files=False,
            key="single_file_uploader",
        )
        if uploaded is not None:
            st.info("已選擇檔案。請到下方頁籤『上傳與分析』使用批次流程（含預覽/確認/執行）。")
        _card_close()

    st.markdown("")
    col_s1, col_s2, col_s3, col_s4 = st.columns(4, gap="large")
    scan = st.session_state.get("folder_scan") or {}
    scan_stats = dict(scan.get("stats") or {}) if isinstance(scan, dict) else {}

    metrics = [
        (col_s1, int(scan_stats.get("scanned_files") or 0), "已掃描檔案數"),
        (col_s2, int(scan_stats.get("stale_candidates") or 0), "久未使用候選"),
        (col_s3, int(len(st.session_state.get("analysis_results") or [])), "待預覽/確認（上傳流程）"),
        (col_s4, int(len(st.session_state.get("execution_results") or [])), "已執行紀錄（本次會話）"),
    ]
    for col, value, label in metrics:
        with col:
            _card_open("status-card")
            st.markdown(f'<div class="status-metric">{value}</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="status-label">{label}</div>', unsafe_allow_html=True)
            _card_close()


_render_home_dashboard()


def _render_upload_tab_impl():
    st.header("上傳與分析（輔助流程）")
    st.markdown("這是用於單檔/批次測試分析品質的流程；首頁主流程以『掃描資料夾』為主。")
    st.caption("支援格式：PDF、JPG/JPEG、PNG、MP4、MOV、MKV")

    uploaded_files = st.file_uploader(
        "選擇檔案",
        type=["pdf", "jpg", "jpeg", "png", "mp4", "mov", "mkv"],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info("請先選擇檔案上傳。")
        return

    st.success(f"✅ 已選擇 {len(uploaded_files)} 個檔案")

    if not st.button("🔍 開始分析", key="analyze_button"):
        return

    _reset_review_state()
    progress_bar = st.progress(0)
    status_text = st.empty()
    uploaded_batch = _build_uploaded_file_batch(uploaded_files)

    def _on_progress(index: int, total: int, uploaded: UploadedFileData):
        progress_bar.progress(index / total)
        status_text.text(f"分析中... {index}/{total} - {uploaded.name}")
        st.session_state.current_processing_file = uploaded.name

    try:
        outcome = analyze_upload_batch(
            uploaded_batch,
            processor=processor,
            storage=storage,
            processing_options=st.session_state.get("processing_options"),
            progress_callback=_on_progress,
        )

        progress_bar.progress(1.0)
        status_text.text("✅ 分析完成！")

        for err in outcome.errors:
            st.error(f"❌ {err}")

        if outcome.duplicates:
            st.warning(f"⚠️ 發現 {len(outcome.duplicates)} 個重複檔案，已跳過")
            for dup in outcome.duplicates:
                if getattr(dup, "status", "") == "COMPLETED":
                    st.info(f"📁 {dup.display} → {dup.final_path or '已整理'}")
                else:
                    st.info(f"⏳ {dup.display}")

        st.session_state.analysis_results = outcome.results

        if outcome.results:
            st.success(f"✅ 成功分析 {len(outcome.results)} 個檔案，請前往『預覽與確認』頁籤")
        else:
            st.warning("⚠️ 未有新檔案可分析")

    except Exception as e:
        logger.exception("分析失敗")
        _handle_ui_exception("分析失敗，請稍後重試或開啟 Debug 模式查看詳細錯誤。", e)


def render_upload_tab():
    try:
        _render_upload_tab_impl()
    except Exception as e:
        logger.exception("render_upload_tab failed")
        _handle_ui_exception("上傳與分析頁面發生錯誤，請重整後再試。", e)


def _render_review_tab_impl():
    st.header("預覽與確認")

    if not st.session_state.get("analysis_results"):
        st.info("尚未有上傳分析結果。若要整理本機資料夾，請先使用首頁的『掃描資料夾』。")
        return

    analysis_results_raw = st.session_state.analysis_results
    if not isinstance(analysis_results_raw, list):
        st.error("分析結果格式錯誤，請回到『上傳與分析』重新分析。")
        if _is_debug():
            st.json({"type": str(type(analysis_results_raw))})
        return

    analysis_results: list[AnalysisResult] = analysis_results_raw
    st.markdown("在下方預覽每個檔案，並確認分類結果。")

    selected_topics: dict[int, str] = {}

    for idx, result in enumerate(analysis_results):
        with st.expander(f"📄 {result.original_name}", expanded=(idx == 0)):
            col1, col2 = st.columns([1, 2])

            with col1:
                st.subheader("預覽")
                is_video = result.file_type == "video"

                if result.preview_path and storage.path_exists(result.preview_path):
                    try:
                        st.image(str(result.preview_path), use_container_width=True)

                        if is_video:
                            st.caption("🎬 影片縮圖")
                    except Exception as e:
                        if _is_debug():
                            st.exception(e)
                        st.info("無預覽圖")
                else:
                    if is_video:
                        st.markdown("🎬 **影片**")
                        try:
                            from core import FFMPEG_AVAILABLE

                            if not FFMPEG_AVAILABLE:
                                st.warning(
                                    "**無法產生影片預覽**\n\n"
                                    "縮圖產生失敗\n\n"
                                    "請安裝 ffmpeg（含 ffprobe）以啟用影片縮圖與 metadata 提取功能"
                                )
                            else:
                                st.info("無縮圖（產生失敗）")
                        except Exception:
                            st.info("無縮圖")
                    else:
                        st.info("無預覽圖")

            with col2:
                st.subheader("詳細資訊")
                st.write(f"**檔名**: {result.original_name}")
                st.write(f"**類型**: {result.file_type}")
                st.write(f"**日期**: {result.standard_date}")

                analysis_status = str(getattr(result, "analysis_status", "OK") or "OK")
                if analysis_status in {"WARNING", "PARTIAL"}:
                    st.warning("此檔案部分分析失敗，但仍可整理。")
                    last_error = getattr(result, "last_error", None)
                    if last_error:
                        st.caption(f"last_error: {last_error}")
                    if _is_debug() and getattr(result, "step_timings", None):
                        st.caption("step_timings")
                        st.json(getattr(result, "step_timings") or {})

                if result.file_type == "video":
                    try:
                        render_video_details(result.metadata or {})
                    except Exception as e:
                        st.warning(f"影片資訊顯示失敗：{e}")

                if result.is_scanned:
                    st.warning("⚠️ 掃描 PDF - 文字不足，已視情況嘗試 OCR 抽樣（可於側邊欄調整/停用）")
                    if (result.metadata or {}).get("ocr_error"):
                        st.error(f"❌ OCR 提示: {result.metadata['ocr_error']}")

                notes = (result.metadata or {}).get("notes")
                if notes:
                    if isinstance(notes, list):
                        st.info("處理提示：\n- " + "\n- ".join(map(str, notes)))
                    else:
                        st.info(f"處理提示：{notes}")

                st.write("**建議標籤**:")
                tag_str = ", ".join(
                    [f"{tag}({score:.0%})" for tag, score in (result.tag_scores or {}).items()]
                )
                st.write(tag_str or "無")

                if result.file_type == "document":
                    tag_options = list(DOCUMENT_TAGS)
                elif result.file_type == "photo":
                    tag_options = list(PHOTO_TAGS)
                elif result.file_type == "video":
                    tag_options = list(VIDEO_TAGS)
                else:
                    tag_options = list(DOCUMENT_TAGS)

                tag_options = list(tag_options)
                if not tag_options:
                    tag_options = ["其他文件"]
                current_index = tag_options.index(result.main_topic) if result.main_topic in tag_options else 0
                current_index = min(max(0, int(current_index)), len(tag_options) - 1)

                new_topic = st.selectbox(
                    "選擇分類",
                    tag_options,
                    index=current_index,
                    key=f"topic_{idx}_{result.file_id}",
                )

                selected_topics[result.file_id] = new_topic

                try:
                    computed = apply_manual_topic_override(
                        result,
                        processor=processor,
                        chosen_topic=new_topic,
                        summary=st.session_state.review_summaries.get(result.file_id),
                    )

                    st.caption("📝 分類理由")
                    st.code(str(computed.classification_reason or ""))
                    st.caption("🎯 最終決策理由")
                    st.code(str(computed.final_decision_reason or ""))

                except Exception as e:
                    logger.exception("分類覆寫失敗")
                    _handle_ui_exception("分類覆寫失敗，請稍後再試或開啟 Debug 模式查看詳細錯誤。", e)
                    computed = result

                if st.button("✨ AI 建議摘要", key=f"summary_{idx}_{result.file_id}"):
                    if not st.session_state.get("ai_enabled"):
                        st.warning("AI 功能未啟用，請在設定中開啟。")
                        continue

                    with st.spinner("生成 AI 摘要建議中..."):
                        try:
                            suggestion = generate_summary_suggestion(
                                computed,
                                processor=processor,
                            )
                            st.info(f"**建議**: {suggestion.summary}")
                            if suggestion.llm_tags:
                                st.caption("AI 同時建議了以下標籤供參考：")
                                st.write(f"**AI 建議標籤**: {', '.join(suggestion.llm_tags)}")
                            st.session_state.review_summaries[result.file_id] = suggestion.summary
                        except Exception as e:
                            logger.exception("AI 摘要失敗")
                            _handle_ui_exception("AI 摘要失敗，請稍後再試或開啟 Debug 模式查看詳細錯誤。", e)

    if st.button("✅ 確認無誤，進行整理", key="confirm_button"):
        try:
            st.session_state.confirmed_results = build_confirmed_results(
                analysis_results,
                processor=processor,
                selected_topics=selected_topics,
                summaries=st.session_state.review_summaries,
            )
            st.success("✅ 已確認！請前往「執行整理」頁籤。")
        except Exception as e:
            logger.exception("建立確認結果失敗")
            _handle_ui_exception("建立確認結果失敗，請稍後再試或開啟 Debug 模式查看詳細錯誤。", e)


def render_review_tab():
    try:
        _render_review_tab_impl()
    except Exception as e:
        logger.exception("render_review_tab failed")
        _handle_ui_exception("預覽與確認頁面發生錯誤，請重整後再試。", e)


def _render_execute_tab_impl():
    st.header("執行整理")

    if not st.session_state.get("confirmed_results"):
        st.info("請先在『預覽與確認』頁籤完成確認。")
        return

    if not st.button("🚀 開始移動檔案", key="execute_button"):
        return

    confirmed_results = st.session_state.confirmed_results
    progress_bar = st.progress(0)
    status_text = st.empty()

    def _on_execute_progress(index: int, total: int, result: AnalysisResult):
        progress_bar.progress(index / total)
        status_text.text(f"整理中... {index}/{total} - {result.original_name}")

    try:
        execution_results = finalize_batch(
            confirmed_results,
            storage=storage,
            progress_callback=_on_execute_progress,
        )

        progress_bar.progress(1.0)
        status_text.text("✅ 整理完成！")

        st.session_state.execution_results = execution_results
        st.session_state.analysis_results = []
        st.session_state.confirmed_results = []
        _reset_review_state()

        for res in execution_results:
            if res.status == "SUCCESS":
                st.success(f"✅ {res.original_name} → {res.new_path}")
            else:
                st.error(f"❌ {res.original_name} 整理失敗（可重試）。詳細原因已記錄在「查看紀錄」的 last_error。")

    except Exception as e:
        logger.exception("整理失敗")
        _handle_ui_exception("整理失敗，請稍後重試或開啟 Debug 模式查看詳細錯誤。", e)


def render_execute_tab():
    try:
        _render_execute_tab_impl()
    except Exception as e:
        logger.exception("render_execute_tab failed")
        _handle_ui_exception("執行整理頁面發生錯誤，請重整後再試。", e)


def _render_search_tab_impl():
    st.header("全文檢索")

    search_query = st.text_input("輸入搜尋關鍵字", placeholder="例如：軟體開發、統編 12345678")

    if not search_query:
        st.info("請輸入搜尋關鍵字。注意：查詢中的部分特殊字元會被忽略；若忽略後沒有任何詞，會回傳空結果。")
        return

    with st.spinner("搜尋中..."):
        try:
            results = storage.search_content(search_query)

            if results:
                st.success(f"✅ 找到 {len(results)} 筆結果")
                for result in results:
                    with st.expander(f"📄 {result['original_name']} ({result['standard_date']})"):
                        st.write(f"**主題**: {result['main_topic']}")
                        st.write(f"**路徑**: {result['final_path']}")

                        if result.get("all_tags"):
                            st.write(f"**標籤**: {result['all_tags']}")

                        st.markdown(f"**內容片段**: ...{result.get('snippet', '')}...")

                        if result.get("final_path") and storage.path_exists(result["final_path"]):
                            with open(result["final_path"], "rb") as f:
                                st.download_button(
                                    "下載檔案",
                                    f,
                                    file_name=os.path.basename(result["final_path"]),
                                    key=f"dl_{result['file_id']}",
                                )
            else:
                st.info("🔎 沒有找到符合的結果。")

        except SearchContentError as e:
            logger.error(f"搜尋失敗: {e}")
            st.error("搜尋暫時不可用，請稍後再試或重建索引。")
        except Exception as e:
            logger.exception("搜尋失敗")
            _handle_ui_exception("搜尋失敗，請稍後再試或開啟 Debug 模式查看詳細錯誤。", e)


def render_search_tab():
    try:
        _render_search_tab_impl()
    except Exception as e:
        logger.exception("render_search_tab failed")
        _handle_ui_exception("全文檢索頁面發生錯誤，請重整後再試。", e)


def _render_records_tab_impl():
    st.header("查看紀錄")

    try:
        records = storage.get_all_records()
    except Exception as e:
        logger.exception("讀取紀錄失敗")
        _handle_ui_exception("讀取紀錄失敗，請稍後再試或開啟 Debug 模式查看詳細錯誤。", e)
        return

    if not records:
        st.info("目前尚無處理紀錄")
        return

    if pd is not None:
        df = pd.DataFrame(records)
        cols = [
            "file_id",
            "original_name",
            "standard_date",
            "main_topic",
            "all_tags",
            "status",
            "manual_override",
            "last_error",
            "created_at",
        ]
        display_df = df[[c for c in cols if c in df.columns]]
        st.dataframe(display_df, use_container_width=True)
    else:
        st.dataframe(records, use_container_width=True)

    st.subheader("維護操作")
    col_a, col_b, col_c = st.columns(3)

    with col_a:
        if st.button("🔁 重新整理檔案位置", key="refresh_locations"):
            with st.spinner("重新整理中..."):
                try:
                    res = storage.refresh_file_locations(fix_moving=True)
                    if res.get("success"):
                        st.success(f"完成：{res.get('summary')}")
                    else:
                        st.error(f"失敗：{res.get('error')}；已檢查：{res.get('summary')}")
                except Exception as e:
                    _handle_ui_exception("重新整理檔案位置失敗。", e)

    with col_b:
        if st.button("🧱 對齊/重建全文索引(FTS)", key="rebuild_fts"):
            with st.spinner("對齊/重建索引中...（不會重新擷取檔案內容）"):
                try:
                    res = storage.reconcile_fts_rows()
                    if res.get("success"):
                        st.success("FTS 索引對齊/重建完成")
                    else:
                        st.error(f"重建失敗：{res.get('error')}")
                except Exception as e:
                    _handle_ui_exception("重建索引失敗。", e)

    with col_c:
        st.caption("重新分類：選一筆紀錄後執行")

    file_id_options = [r.get("file_id") for r in records if r.get("file_id") is not None]

    if file_id_options:
        selected_file_id = st.selectbox("選擇 file_id", file_id_options, index=0, key="reclassify_file_id")

        if st.button("🏷️ 重新分類（不使用 AI）", key="do_reclassify"):
            with st.spinner("重新分類中..."):
                try:
                    main_topic = reclassify_record(
                        storage=storage,
                        processor=processor,
                        file_id=int(selected_file_id),
                        processing_options=st.session_state.get("processing_options"),
                    )
                    st.success(f"重新分類完成：{main_topic}")
                except FileNotFoundError:
                    st.error("檔案不存在（可能已遺失），請先用「重新整理檔案位置」檢查。")
                except Exception as e:
                    logger.exception("重新分類失敗")
                    _handle_ui_exception("重新分類失敗。", e)
    else:
        st.info("沒有可重新分類的紀錄")

    if pd is not None:
        st.subheader("統計分析")
        col1, col2 = st.columns(2)

        with col1:
            st.write("**主題分佈**")
            if "main_topic" in df.columns:
                topic_series = df["main_topic"]
                if topic_series is not None:
                    topic_counts = (
                        topic_series.dropna()
                        .astype(str)
                        .replace("", pd.NA)
                        .dropna()
                        .value_counts()
                    )
                    if not topic_counts.empty:
                        st.bar_chart(topic_counts)
                    else:
                        st.info("沒有可用的主題資料可畫圖。")
            else:
                st.info("沒有 main_topic 欄位，略過圖表。")

        with col2:
            st.write("**處理狀態**")
            if "status" in df.columns:
                status_series = df["status"]
                if status_series is not None:
                    status_counts = (
                        status_series.dropna()
                        .astype(str)
                        .replace("", pd.NA)
                        .dropna()
                        .value_counts()
                    )
                    if status_counts.empty:
                        st.info("沒有可用的狀態資料可畫圖。")
                    elif plt is None:
                        st.bar_chart(status_counts)
                    else:
                        fig, ax = plt.subplots()
                        status_counts.plot.pie(ax=ax, autopct="%1.1f%%", startangle=90)
                        ax.set_ylabel("")
                        st.pyplot(fig)
                        plt.close(fig)
            else:
                st.info("沒有 status 欄位，略過圖表。")


def render_records_tab():
    try:
        _render_records_tab_impl()
    except Exception as e:
        logger.exception("render_records_tab failed")
        _handle_ui_exception("查看紀錄頁面發生錯誤，請重整後再試。", e)


tab1, tab2, tab3, tab4, tab5 = st.tabs(
    ["📤 上傳與分析（輔助）", "👁️ 預覽與確認", "✅ 執行整理", "🔍 全文檢索", "📊 查看紀錄"]
)

with tab1:
    render_upload_tab()

with tab2:
    render_review_tab()

with tab3:
    render_execute_tab()

with tab4:
    render_search_tab()

with tab5:
    render_records_tab()

st.divider()
st.caption(f"{APP_NAME} v{__version__} | Powered by Python & Streamlit")
