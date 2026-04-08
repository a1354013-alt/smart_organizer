import streamlit as st
import os
import logging

try:
    import pandas as pd  # type: ignore
except Exception:  # pragma: no cover
    pd = None  # type: ignore

try:
    import matplotlib.pyplot as plt  # type: ignore
except Exception:  # pragma: no cover
    plt = None  # type: ignore
from pathlib import Path
from core import FileProcessor, DOCUMENT_TAGS, PHOTO_TAGS, FileUtils
from logging_config import setup_logging
from storage import StorageManager, SearchContentError

# ========== 路徑配置 (集中管理) ==========
PROJECT_ROOT = Path(__file__).parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
REPO_ROOT = PROJECT_ROOT / "repo"
DB_PATH = PROJECT_ROOT / "smart_organizer.db"

# 設定 Logging
setup_logging()
logger = logging.getLogger(__name__)

# 初始化
processor = FileProcessor()
storage = StorageManager(str(DB_PATH), str(REPO_ROOT), str(UPLOAD_DIR))

st.set_page_config(page_title="智慧檔案整理助理", layout="wide")
st.title("📁 智慧檔案整理助理 (v2.7.4 Steel-Fortified Final Ultimate)")
st.markdown("**資料庫驅動的檔案生命週期管理系統 - 鋼鐵堡壘最終究極版**\n- 狀態機收斂補強 | FTS 查詢防禦 | 極致乾淨打包 | OpenAI Timeout")

def _init_session_state():
    st.session_state.setdefault("analysis_results", [])
    st.session_state.setdefault("confirmed_results", [])
    st.session_state.setdefault("execution_results", [])
    st.session_state.setdefault("cleanup_actions", [])


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
    st.markdown("支援格式：PDF、JPG、PNG")

    uploaded_files = st.file_uploader(
        "選擇檔案",
        type=["pdf", "jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )

    if not uploaded_files:
        st.info("請先選擇檔案上傳。")
        return

    st.success(f"✅ 已選擇 {len(uploaded_files)} 個檔案")

    if not st.button("🔍 開始分析", key="analyze_button"):
        return

    progress_bar = st.progress(0)
    status_text = st.empty()
    analysis_results = []
    duplicates = []

    for idx, uploaded_file in enumerate(uploaded_files):
        progress = (idx + 1) / len(uploaded_files)
        progress_bar.progress(progress)
        status_text.text(f"分析中... {idx + 1}/{len(uploaded_files)}")

        try:
            file_hash = processor.get_file_hash(uploaded_file)

            result = storage.create_temp_file(
                uploaded_file.name,
                uploaded_file.getbuffer(),
                file_hash,
                "photo" if uploaded_file.type.startswith("image") else "document",
            )

            if not result["success"]:
                if result.get("reason") == "DUPLICATE":
                    dup_status = result.get("status", "UNKNOWN")
                    dup_name = uploaded_file.name
                    if dup_status == "COMPLETED":
                        duplicates.append({
                            "filename": uploaded_file.name,
                            "status": "COMPLETED",
                            "path": result.get("final_path", "已整理"),
                            "display": f"{dup_name} (已整理)",
                        })
                    else:
                        duplicates.append({
                            "filename": uploaded_file.name,
                            "status": "PENDING",
                            "display": f"{dup_name} (已在待整理清單)",
                        })
                else:
                    st.error(f"❌ 建立暫存檔失敗: {uploaded_file.name} - {result.get('message')}")
                continue

            file_id = result["file_id"]
            temp_file_path = storage.get_file_path(file_id)

            metadata = processor.extract_metadata(temp_file_path, st.session_state.get("processing_options"))
            main_topic, tag_scores, classification_reason = processor.classify_multi_tag(
                metadata,
                uploaded_file.name,
                return_reason=True,
            )

            metadata["standard_date"] = FileUtils.normalize_standard_date(metadata["standard_date"])

            analysis_results.append({
                "file_id": file_id,
                "original_name": uploaded_file.name,
                "file_type": metadata["file_type"],
                "standard_date": metadata["standard_date"],
                "main_topic": main_topic,
                "suggested_main_topic": main_topic,
                "tag_scores": tag_scores,
                "classification_reason": classification_reason,
                "final_decision_reason": "採用規則建議",
                "metadata": metadata,
                "preview_path": metadata.get("preview_path"),
                "is_scanned": metadata.get("is_scanned", False),
            })

        except Exception as e:
            logger.error(f"分析失敗 ({uploaded_file.name}): {e}")
            st.error(f"❌ 分析失敗: {uploaded_file.name} - {e}")

    progress_bar.progress(1.0)
    status_text.text("✅ 分析完成！")

    if duplicates:
        st.warning(f"⚠️ 發現 {len(duplicates)} 個重複檔案，已跳過")
        for dup in duplicates:
            if dup["status"] == "COMPLETED":
                st.info(f"📁 {dup['display']} → {dup.get('path', '已整理')}")
            else:
                st.info(f"⏳ {dup['display']}")

    st.session_state.analysis_results = analysis_results

    if analysis_results:
        st.success(f"✅ 成功分析 {len(analysis_results)} 個檔案，請前往『預覽與確認』頁籤")
    else:
        st.warning("⚠️ 未有新檔案可分析")


def render_review_tab():
    st.header("步驟 2：預覽與確認")

    if "analysis_results" not in st.session_state or not st.session_state.analysis_results:
        st.info("請先在『上傳與分析』頁籤上傳檔案。")
        return

    analysis_results = st.session_state.analysis_results
    st.markdown("在下方預覽每個檔案，並確認分類結果。")

    for idx, result in enumerate(analysis_results):
        with st.expander(f"📄 {result['original_name']}", expanded=(idx == 0)):
            col1, col2 = st.columns([1, 2])

            with col1:
                st.subheader("預覽")
                if result["preview_path"] and os.path.exists(result["preview_path"]):
                    try:
                        from PIL import Image  # type: ignore

                        img = Image.open(result["preview_path"])
                        st.image(img, use_container_width=True)
                    except Exception as e:
                        st.warning(f"預覽失敗: {e}")
                else:
                    st.info("無預覽圖")

            with col2:
                st.subheader("詳細資訊")
                st.write(f"**檔名**: {result['original_name']}")
                st.write(f"**類型**: {result['file_type']}")
                st.write(f"**日期**: {result['standard_date']}")

                if result["is_scanned"]:
                    st.warning("⚠️ 掃描 PDF - 文字不足，已視情況嘗試 OCR 抽樣（可於側邊欄調整/停用）")
                    if result["metadata"].get("ocr_error"):
                        st.error(f"❌ OCR 提示: {result['metadata']['ocr_error']}")

                if result["metadata"].get("notes"):
                    st.info("處理提示：\n- " + "\n- ".join(result["metadata"]["notes"]))

                st.write("**建議標籤**:")
                tag_str = ", ".join([f"{tag}({score:.0%})" for tag, score in result["tag_scores"].items()])
                st.write(tag_str)

                tag_options = DOCUMENT_TAGS if result["file_type"] == "document" else PHOTO_TAGS
                new_topic = st.selectbox(
                    "選擇主題",
                    tag_options,
                    index=tag_options.index(result["main_topic"]) if result["main_topic"] in tag_options else 0,
                    key=f"topic_{idx}",
                )

                suggested = result.get("suggested_main_topic", result["main_topic"])
                if new_topic != suggested:
                    result["final_decision_reason"] = f"手動覆寫：選擇「{new_topic}」（規則建議「{suggested}」）"
                    result["manual_override"] = True
                else:
                    result["final_decision_reason"] = "採用規則建議"
                    result["manual_override"] = False

                result["main_topic"] = new_topic
                result["tag_scores"] = processor.sync_manual_topic(
                    new_topic,
                    result.get("tag_scores"),
                    result["file_type"],
                )

                st.caption("規則推論原因（rule_reason）：")
                st.code(result.get("classification_reason") or "")
                st.caption("最終採用原因（final_decision）：")
                st.code(result.get("final_decision_reason") or "")

                if st.button("🤖 生成 AI 摘要", key=f"summary_{idx}"):
                    if not st.session_state.get("ai_enabled"):
                        st.warning("AI 摘要未啟用：為保護隱私，系統不會送出任何內容。請到側邊欄開啟後再試。")
                        continue

                    with st.spinner("正在生成摘要..."):
                        summary, llm_tags = processor.get_llm_summary(
                            result["metadata"].get("extracted_text", ""),
                            result["file_type"],
                            enabled=True,
                        )
                        st.info(f"**摘要**: {summary}")
                        if llm_tags:
                            st.caption("AI 建議標籤僅供參考，不會自動套用到分類/標籤。")
                            st.write(f"**AI 建議標籤**: {', '.join(llm_tags)}")
                        result["summary"] = summary

    if st.button("✅ 確認無誤，進行整理", key="confirm_button"):
        st.session_state.confirmed_results = analysis_results
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
    execution_results = []

    for idx, result in enumerate(confirmed_results):
        progress = (idx + 1) / len(confirmed_results)
        progress_bar.progress(progress)
        status_text.text(f"整理中... {idx + 1}/{len(confirmed_results)}")

        try:
            storage.update_file_metadata(result["file_id"], {
                "standard_date": result["standard_date"],
                "main_topic": result["main_topic"],
                "summary": result.get("summary", ""),
                "content": result["metadata"].get("extracted_text", ""),
                "is_scanned": result.get("is_scanned", False),
                "preview_path": result.get("preview_path"),
                "classification_reason": result.get("classification_reason"),
                "final_decision_reason": result.get("final_decision_reason"),
                "manual_override": result.get("manual_override"),
                "tag_scores": result.get("tag_scores", {}),
            })

            final_path = storage.finalize_organization(
                result["file_id"],
                result["standard_date"],
                result["main_topic"],
                result["original_name"],
            )

            execution_results.append({
                "original_name": result["original_name"],
                "new_path": final_path,
                "status": "SUCCESS",
            })
        except Exception as e:
            logger.error(f"整理失敗 ({result['file_id']}): {e}")
            execution_results.append({
                "original_name": result["original_name"],
                "file_id": result.get("file_id"),
                "status": "FAILED",
            })

    progress_bar.progress(1.0)
    status_text.text("✅ 整理完成！")

    st.session_state.execution_results = execution_results
    st.session_state.analysis_results = []
    st.session_state.confirmed_results = []

    for res in execution_results:
        if res["status"] == "SUCCESS":
            st.success(f"✅ {res['original_name']} → {res['new_path']}")
        else:
            st.error(f"❌ {res['original_name']} 整理失敗（可重試）。詳細原因已記錄在「查看紀錄」的 last_error。")


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

                        if result.get("final_path") and os.path.exists(result["final_path"]):
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
                info = storage.get_file_by_id(int(selected_file_id))
                if not info:
                    st.error("找不到該筆紀錄")
                else:
                    path = info.get("final_path") or info.get("temp_path")
                    if not path or not storage._path_exists(path):
                        st.error("檔案不存在（可能已遺失），請先用「重新整理檔案位置」檢查。")
                    else:
                        metadata = processor.extract_metadata(path, st.session_state.get("processing_options"))
                        main_topic, tag_scores, reason = processor.classify_multi_tag(
                            metadata,
                            info.get("original_name") or os.path.basename(path),
                            return_reason=True,
                        )
                        storage.update_file_metadata(int(selected_file_id), {
                            "standard_date": metadata.get("standard_date"),
                            "main_topic": main_topic,
                            "summary": info.get("summary") or "",
                            "content": metadata.get("extracted_text") or "",
                            "is_scanned": metadata.get("is_scanned") or False,
                            "preview_path": metadata.get("preview_path"),
                            "classification_reason": reason,
                            "final_decision_reason": "重新分類（規則引擎）",
                            "manual_override": False,
                            "tag_scores": tag_scores,
                        })
                        st.success(f"重新分類完成：{main_topic}")
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
st.caption("智慧檔案整理助理 v2.7.4 Steel-Fortified Final Ultimate | Powered by Python & Streamlit")
