import streamlit as st
import os
import logging

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore[assignment]

try:
    import matplotlib.pyplot as plt
except Exception:  # pragma: no cover
    plt = None  # type: ignore[assignment]
from pathlib import Path
from core import FileProcessor, DOCUMENT_TAGS, PHOTO_TAGS, VIDEO_TAGS
from logging_config import setup_logging
from storage import StorageManager, SearchContentError
from version import APP_NAME, APP_TITLE, __version__
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

# ========== 路徑配置 (集中管理) ==========
PROJECT_ROOT = Path(__file__).parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
REPO_ROOT = PROJECT_ROOT / "repo"
DB_PATH = PROJECT_ROOT / "smart_organizer.db"

# 設定 Logging
setup_logging()
logger = logging.getLogger(__name__)

@st.cache_resource
def _bootstrap_services():
    # Streamlit rerun-safe: cache expensive/side-effectful init once per session.
    processor = FileProcessor()
    storage = StorageManager(str(DB_PATH), str(REPO_ROOT), str(UPLOAD_DIR))
    return processor, storage


processor, storage = _bootstrap_services()

st.set_page_config(page_title=APP_NAME, layout="wide")
st.title(f"📁 {APP_TITLE}")
st.markdown("**資料庫驅動的檔案生命週期管理系統**\n- 規則分類 | OCR/PDF 可降級 | 全文檢索 | 可重試與可診斷（last_error）")

def _init_session_state():
    st.session_state.setdefault("analysis_results", [])
    st.session_state.setdefault("confirmed_results", [])
    st.session_state.setdefault("execution_results", [])
    st.session_state.setdefault("cleanup_actions", [])
    st.session_state.setdefault("review_summaries", {})


def _reset_review_state():
    st.session_state.review_summaries = {}


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
    st.sidebar.header("⚙️ 設定與維護")

    st.sidebar.subheader("AI 摘要")
    ai_enabled = st.sidebar.toggle("啟用 AI 摘要（會送出內容到 OpenAI）", value=False)
    st.sidebar.caption("未啟用時，系統不會送出任何內容。")

    st.sidebar.subheader("效能與安全")
    enable_pdf_preview = st.sidebar.checkbox("啟用 PDF 預覽（需要 poppler）", value=True)
    enable_ocr = st.sidebar.checkbox("啟用 OCR（需要 tesseract）", value=False)
    max_heavy_mb = st.sidebar.slider("耗時處理檔案大小上限 (MB)", 1, 200, 15)
    pdf_text_max_pages = st.sidebar.slider("PDF 文字抽取頁數上限", 1, 50, 10)
    pdf_ocr_max_pages = st.sidebar.slider("PDF OCR 頁數上限", 1, 5, int(getattr(processor, "pdf_ocr_max_pages", 3)))

    processing_options = {
        "enable_pdf_preview": enable_pdf_preview,
        "enable_ocr": enable_ocr,
        "max_heavy_bytes": int(max_heavy_mb) * 1024 * 1024,
        "pdf_text_max_pages": int(pdf_text_max_pages),
        "pdf_ocr_max_pages": int(pdf_ocr_max_pages),
        "pdf_preview_max_pages": int(getattr(processor, "pdf_preview_max_pages", 1)),
    }
    st.session_state.ai_enabled = ai_enabled
    st.session_state.processing_options = processing_options

    with st.sidebar.expander("🔎 環境與依賴檢查", expanded=False):
        deps = processor.get_dependency_status()
        st.write("Python 套件：", deps.get("python", {}))
        st.write("系統依賴：", deps.get("system", {}))
        st.write("設定：", deps.get("config", {}))

    st.sidebar.subheader("🧹 uploads 清理")
    cleanup_dry_run = st.sidebar.checkbox("Dry-run（只預覽不刪除）", value=True)
    if st.sidebar.button("🧹 掃描孤兒暫存檔/預覽圖", key="scan_orphans"):
        try:
            actions = storage.cleanup_orphaned_uploads(dry_run=True)
            st.session_state.cleanup_actions = actions
            st.sidebar.success(f"✅ 掃描完成：{len(actions)} 個待清理項目")
        except Exception as e:
            st.sidebar.error(f"❌ 掃描失敗: {e}")

    if st.sidebar.button("🗑️ 執行清理", key="do_cleanup", disabled=cleanup_dry_run):
        try:
            actions = storage.cleanup_orphaned_uploads(dry_run=False)
            st.session_state.cleanup_actions = actions
            st.sidebar.success(f"✅ 清理完成：{len(actions)} 個項目")
        except Exception as e:
            st.sidebar.error(f"❌ 清理失敗: {e}")

    if st.session_state.get("cleanup_actions"):
        with st.sidebar.expander("待清理清單", expanded=False):
            for a in st.session_state.cleanup_actions[:50]:
                st.write(f"- {a.get('type')}: {a.get('path')}")
            if len(st.session_state.cleanup_actions) > 50:
                st.write(f"...（共 {len(st.session_state.cleanup_actions)} 項，僅顯示前 50）")

    st.sidebar.markdown(
        f"**系統配置**\n- 專案根: `{PROJECT_ROOT}`\n- 上傳目錄: `{UPLOAD_DIR}`\n- 儲存庫: `{REPO_ROOT}`\n- 資料庫: `{DB_PATH}`"
    )


_init_session_state()
_render_sidebar()

# ========== 主流程 ==========
def render_upload_tab():
    st.header("步驟 1：上傳檔案")
    st.markdown("支援格式：PDF、JPG/JPEG、PNG、MP4、MOV、MKV")

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


def render_review_tab():
    st.header("步驟 2：預覽與確認")

    if "analysis_results" not in st.session_state or not st.session_state.analysis_results:
        st.info("請先在『上傳與分析』頁籤上傳檔案。")
        return

    analysis_results: list[AnalysisResult] = st.session_state.analysis_results
    st.markdown("在下方預覽每個檔案，並確認分類結果。")

    selected_topics: dict[int, str] = {}

    for idx, result in enumerate(analysis_results):
        with st.expander(f"📄 {result.original_name}", expanded=(idx == 0)):
            col1, col2 = st.columns([1, 2])

            with col1:
                st.subheader("預覽")
                
                # Check if it's a video file
                is_video = result.file_type == "video"
                
                if result.preview_path and storage.path_exists(result.preview_path):
                    try:
                        from PIL import Image

                        img = Image.open(result.preview_path)
                        st.image(img, use_container_width=True)
                        
                        # Show video badge for videos
                        if is_video:
                            st.caption("🎬 影片縮圖")
                    except Exception as e:
                        st.warning(f"預覽失敗：{e}")
                else:
                    # No thumbnail available
                    if is_video:
                        # Show video placeholder with ffmpeg warning
                        st.markdown("🎬 **影片**")
                        from core import FFMPEG_AVAILABLE
                        if not FFMPEG_AVAILABLE:
                            st.warning("**無法產生影片預覽**\n\n縮圖產生失敗\n\n請安裝 ffmpeg 以啟用影片縮圖與 metadata 提取功能")
                        else:
                            st.info("無縮圖（產生失敗）")
                    else:
                        st.info("無預覽圖")

            with col2:
                st.subheader("詳細資訊")
                st.write(f"**檔名**: {result.original_name}")
                st.write(f"**類型**: {result.file_type}")
                st.write(f"**日期**: {result.standard_date}")

                # Video metadata display (Phase 1 UI completion)
                if result.file_type == "video":
                    extra = (result.metadata or {}).get("extra", {})
                    
                    # Duration formatting (mm:ss)
                    duration_sec = extra.get("duration_seconds")
                    if duration_sec is not None:
                        try:
                            duration_min = int(duration_sec // 60)
                            duration_sec_remainder = int(duration_sec % 60)
                            st.write(f"**時長**: {duration_min:02d}:{duration_sec_remainder:02d}")
                        except (TypeError, ValueError):
                            st.write("**時長**: N/A")
                    else:
                        st.write("**時長**: N/A")
                    
                    # Resolution
                    width = extra.get("width")
                    height = extra.get("height")
                    if width is not None and height is not None:
                        st.write(f"**解析度**: {width} x {height}")
                    else:
                        st.write("**解析度**: N/A")
                    
                    # FPS
                    fps = extra.get("fps")
                    if fps is not None:
                        try:
                            st.write(f"**FPS**: {int(round(float(fps)))}")
                        except (TypeError, ValueError):
                            st.write("**FPS**: N/A")
                    else:
                        st.write("**FPS**: N/A")
                    
                    # Codec
                    codec = extra.get("video_codec")
                    if codec:
                        codec_display = codec.upper() if isinstance(codec, str) else str(codec)
                        st.write(f"**編碼**: {codec_display}")
                    else:
                        st.write("**編碼**: N/A")
                    
                    # File size (from extra or compute from original)
                    file_size = extra.get("file_size")
                    if file_size is not None:
                        try:
                            file_size_mb = float(file_size) / (1024 * 1024)
                            if file_size_mb >= 1:
                                st.write(f"**大小**: {file_size_mb:.1f} MB")
                            else:
                                st.write(f"**大小**: {file_size / 1024:.1f} KB")
                        except (TypeError, ValueError):
                            st.write("**大小**: N/A")
                    else:
                        st.write("**大小**: N/A")
                    
                    # Thumbnail error warning if present
                    thumb_error = extra.get("thumbnail_error")
                    if thumb_error:
                        st.warning(f"縮圖提示：{thumb_error}")


                if result.is_scanned:
                    st.warning("⚠️ 掃描 PDF - 文字不足，已視情況嘗試 OCR 抽樣（可於側邊欄調整/停用）")
                    if (result.metadata or {}).get("ocr_error"):
                        st.error(f"❌ OCR 提示: {result.metadata['ocr_error']}")

                if (result.metadata or {}).get("notes"):
                    st.info("處理提示：\n- " + "\n- ".join(result.metadata["notes"]))

                st.write("**建議標籤**:")
                tag_str = ", ".join([f"{tag}({score:.0%})" for tag, score in (result.tag_scores or {}).items()])
                st.write(tag_str)

                # Three-way classification分流：document/photo/video
                if result.file_type == "document":
                    tag_options = DOCUMENT_TAGS
                elif result.file_type == "photo":
                    tag_options = PHOTO_TAGS
                elif result.file_type == "video":
                    tag_options = VIDEO_TAGS
                else:
                    tag_options = DOCUMENT_TAGS  # fallback
                
                new_topic = st.selectbox(
                    "選擇分類",
                    tag_options,
                    index=tag_options.index(result.main_topic) if result.main_topic in tag_options else 0,
                    key=f"topic_{idx}",
                )
                selected_topics[result.file_id] = new_topic

                # Keep decision updates inside service/usecase instead of mutating AnalysisResult in UI.
                computed = apply_manual_topic_override(
                    result,
                    processor=processor,
                    chosen_topic=new_topic,
                    summary=st.session_state.review_summaries.get(result.file_id),
                )

                st.caption("📝 分類理由")
                st.code(computed.classification_reason or "")
                st.caption("🎯 最終決策理由")
                st.code(computed.final_decision_reason or "")

                if st.button("✨ AI 建議摘要", key=f"summary_{idx}"):
                    if not st.session_state.get("ai_enabled"):
                        st.warning("AI 功能未啟用，請在設定中開啟。")
                        continue

                    with st.spinner("生成 AI 摘要建議中..."):
                        suggestion = generate_summary_suggestion(
                            computed,
                            processor=processor,
                        )
                        st.info(f"**建議**: {suggestion.summary}")
                        if suggestion.llm_tags:
                            st.caption("AI 同時建議了以下標籤供參考：")
                            st.write(f"**AI 建議標籤**: {', '.join(suggestion.llm_tags)}")
                        st.session_state.review_summaries[result.file_id] = suggestion.summary

    if st.button("✅ 確認無誤，進行整理", key="confirm_button"):
        st.session_state.confirmed_results = build_confirmed_results(
            analysis_results,
            processor=processor,
            selected_topics=selected_topics,
            summaries=st.session_state.review_summaries,
        )
        st.success("✅ 已確認！請前往「執行整理」頁籤。")


def render_execute_tab():
    st.header("步驟 3：執行整理")

    if "confirmed_results" not in st.session_state or not st.session_state.confirmed_results:
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


def render_search_tab():
    st.header("步驟 4：全文檢索")

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
            logger.error(f"搜尋失敗: {e}")
            st.error("搜尋暫時不可用，請稍後再試。")


def render_records_tab():
    st.header("步驟 5：查看紀錄")

    records = storage.get_all_records()
    if not records:
        st.info("目前尚無處理紀錄")
        return

    if pd is not None:
        df = pd.DataFrame(records)
        cols = ["file_id", "original_name", "standard_date", "main_topic", "all_tags", "status", "manual_override", "last_error", "created_at"]
        display_df = df[[c for c in cols if c in df.columns]]
        st.dataframe(display_df, use_container_width=True)
    else:
        st.dataframe(records, use_container_width=True)

    st.subheader("維護操作")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("🔁 重新整理檔案位置", key="refresh_locations"):
            with st.spinner("重新整理中..."):
                res = storage.refresh_file_locations(fix_moving=True)
                if res.get("success"):
                    st.success(f"完成：{res.get('summary')}")
                else:
                    st.error(f"失敗：{res.get('error')}；已檢查：{res.get('summary')}")
    with col_b:
        if st.button("🧱 重建全文索引(FTS)", key="rebuild_fts"):
            with st.spinner("重建索引中..."):
                res = storage.rebuild_fts_index()
                if res.get("success"):
                    st.success("FTS 索引重建完成")
                else:
                    st.error(f"重建失敗：{res.get('error')}")
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
                    logger.error(f"重新分類失敗: {e}")
                    st.error("重新分類失敗，請稍後再試。")
    else:
        st.info("沒有可重新分類的紀錄")

    if pd is not None:
        st.subheader("統計分析")
        col1, col2 = st.columns(2)
        with col1:
            st.write("**主題分佈**")
            topic_counts = df["main_topic"].value_counts()
            st.bar_chart(topic_counts)
        with col2:
            st.write("**處理狀態**")
            status_counts = df["status"].value_counts()
            if plt is None:
                st.bar_chart(status_counts)
            else:
                fig, ax = plt.subplots()
                status_counts.plot.pie(ax=ax, autopct="%1.1f%%", startangle=90)
                ax.set_ylabel("")
                st.pyplot(fig)
                plt.close(fig)


tab1, tab2, tab3, tab4, tab5 = st.tabs(["📤 上傳與分析", "👁️ 預覽與確認", "✅ 執行整理", "🔍 全文檢索", "📊 查看紀錄"])

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
