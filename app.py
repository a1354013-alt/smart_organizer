import streamlit as st
import os
import logging
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
from core import FileProcessor, FileUtils, DOCUMENT_TAGS, PHOTO_TAGS
from storage import StorageManager

# ========== 路徑配置 (集中管理) ==========
PROJECT_ROOT = Path(__file__).parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
REPO_ROOT = PROJECT_ROOT / "repo"
DB_PATH = PROJECT_ROOT / "smart_organizer.db"

# 設定 Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化
processor = FileProcessor()
storage = StorageManager(str(DB_PATH), str(REPO_ROOT), str(UPLOAD_DIR))

st.set_page_config(page_title="智慧檔案整理助理", layout="wide")
st.title("📁 智慧檔案整理助理 (v2.7.1 Steel-Fortified Hotfix)")
st.markdown("**資料庫驅動的檔案生命週期管理系統 - 鋼鐵堡壘修正版**\n- 強化 Recovery 邏輯 | 補全依賴 | 預覽圖清理優化 | OpenAI Timeout")

# ========== Sidebar 配置 ==========
st.sidebar.header("⚙️ 設定與維護")
if st.sidebar.button("🧹 清理孤立暫存檔"):
    try:
        storage.cleanup_orphaned_uploads()
        st.sidebar.success("✅ 清理完成")
    except Exception as e:
        st.sidebar.error(f"❌ 清理失敗: {e}")

st.sidebar.markdown(f"**系統配置**\n- 專案根: `{PROJECT_ROOT}`\n- 上傳目錄: `{UPLOAD_DIR}`\n- 儲存庫: `{REPO_ROOT}`\n- 資料庫: `{DB_PATH}`")

# ========== 主流程 ==========
tab1, tab2, tab3, tab4, tab5 = st.tabs(["📤 上傳與分析", "👁️ 預覽與確認", "✅ 執行整理", "🔍 全文檢索", "📊 查看紀錄"])

with tab1:
    st.header("步驟 1：上傳檔案")
    st.markdown("支援格式：PDF、JPG、PNG")
    
    uploaded_files = st.file_uploader(
        "選擇檔案",
        type=['pdf', 'jpg', 'jpeg', 'png'],
        accept_multiple_files=True
    )
    
    if uploaded_files:
        st.success(f"✅ 已選擇 {len(uploaded_files)} 個檔案")
        
        if st.button("🔍 開始分析", key="analyze_button"):
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
                    
                    # 【優化】由 Storage 層建立暫存檔，並處理併發衝突
                    result = storage.create_temp_file(
                        uploaded_file.name,
                        uploaded_file.getbuffer(),
                        file_hash,
                        'photo' if uploaded_file.type.startswith('image') else 'document'
                    )
                    
                    if not result["success"]:
                        if result.get("reason") == "DUPLICATE":
                            dup_status = result.get('status', 'UNKNOWN')
                            dup_name = uploaded_file.name
                            if dup_status == 'COMPLETED':
                                duplicates.append({
                                    'filename': uploaded_file.name,
                                    'status': 'COMPLETED',
                                    'path': result.get('final_path', '已整理'),
                                    'display': f"{dup_name} (已整理)"
                                })
                            else:
                                duplicates.append({
                                    'filename': uploaded_file.name,
                                    'status': 'PENDING',
                                    'display': f"{dup_name} (已在待整理清單)"
                                })
                        else:
                            st.error(f"❌ 建立暫存檔失敗: {uploaded_file.name} - {result.get('message')}")
                        continue
                    
                    file_id = result["file_id"]
                    temp_file_path = storage.get_file_path(file_id)
                    
                    # 提取中繼資料
                    metadata = processor.extract_metadata(temp_file_path)
                    main_topic, tag_scores = processor.classify_multi_tag(metadata, uploaded_file.name)
                    
                    if metadata['standard_date'] is None:
                        metadata['standard_date'] = 'UnknownDate'
                    
                    analysis_results.append({
                        'file_id': file_id,
                        'original_name': uploaded_file.name,
                        'file_type': metadata['file_type'],
                        'standard_date': metadata['standard_date'],
                        'main_topic': main_topic,
                        'tag_scores': tag_scores,
                        'metadata': metadata,
                        'preview_path': metadata.get('preview_path'),
                        'is_scanned': metadata.get('is_scanned', False)
                    })
                
                except Exception as e:
                    logger.error(f"分析失敗 ({uploaded_file.name}): {e}")
                    st.error(f"❌ 分析失敗: {uploaded_file.name} - {e}")
            
            progress_bar.progress(1.0)
            status_text.text("✅ 分析完成！")
            
            if duplicates:
                st.warning(f"⚠️ 發現 {len(duplicates)} 個重複檔案，已跳過")
                for dup in duplicates:
                    if dup['status'] == 'COMPLETED':
                        st.info(f"📁 {dup['display']} → {dup.get('path', '已整理')}")
                    else:
                        st.info(f"⏳ {dup['display']}")
            
            st.session_state.analysis_results = analysis_results
            
            if analysis_results:
                st.success(f"✅ 成功分析 {len(analysis_results)} 個檔案，請前往『預覽與確認』頁籤")
            else:
                st.warning("⚠️ 未有新檔案可分析")

with tab2:
    st.header("步驟 2：預覽與確認")
    
    if 'analysis_results' in st.session_state and st.session_state.analysis_results:
        analysis_results = st.session_state.analysis_results
        
        st.markdown("在下方預覽每個檔案，並確認分類結果")
        
        for idx, result in enumerate(analysis_results):
            with st.expander(f"📄 {result['original_name']}", expanded=(idx == 0)):
                col1, col2 = st.columns([1, 2])
                
                with col1:
                    st.subheader("預覽")
                    if result['preview_path'] and os.path.exists(result['preview_path']):
                        try:
                            from PIL import Image
                            img = Image.open(result['preview_path'])
                            st.image(img, use_column_width=True)
                        except Exception as e:
                            st.warning(f"預覽失敗: {e}")
                    else:
                        st.info("無預覽圖")
                
                with col2:
                    st.subheader("詳細資訊")
                    st.write(f"**檔名**: {result['original_name']}")
                    st.write(f"**類型**: {result['file_type']}")
                    st.write(f"**日期**: {result['standard_date']}")
                    
                    if result['is_scanned']:
                        st.warning("⚠️ 掃描 PDF - 已執行第一頁 OCR，可進行搜尋與分類")
                        if result['metadata'].get('ocr_error'):
                            st.error(f"❌ OCR 提示: {result['metadata']['ocr_error']}")
                    
                    st.write("**建議標籤**:")
                    tag_str = ", ".join([f"{tag}({score:.0%})" for tag, score in result['tag_scores'].items()])
                    st.write(tag_str)
                    
                    tag_options = DOCUMENT_TAGS if result['file_type'] == 'document' else PHOTO_TAGS
                    new_topic = st.selectbox(
                        "選擇主題",
                        tag_options,
                        index=tag_options.index(result['main_topic']) if result['main_topic'] in tag_options else 0,
                        key=f"topic_{idx}"
                    )
                    result['main_topic'] = new_topic
                    
                    if st.button(f"🤖 生成 AI 摘要", key=f"summary_{idx}"):
                        with st.spinner("正在生成摘要..."):
                            summary, llm_tags = processor.get_llm_summary(
                                result['metadata'].get('extracted_text', '')[:2000],
                                result['file_type']
                            )
                            st.info(f"**摘要**: {summary}")
                            if llm_tags:
                                st.write(f"**AI 建議標籤**: {', '.join(llm_tags)}")
                            result['summary'] = summary
        
        if st.button("✅ 確認無誤，進行整理", key="confirm_button"):
            st.session_state.confirmed_results = analysis_results
            st.success("✅ 已確認！請前往「執行整理」頁籤")
    else:
        st.info("請先在「上傳與分析」頁籤上傳檔案")

with tab3:
    st.header("步驟 3：執行整理")
    
    if 'confirmed_results' in st.session_state and st.session_state.confirmed_results:
        if st.button("🚀 開始移動檔案", key="execute_button"):
            confirmed_results = st.session_state.confirmed_results
            progress_bar = st.progress(0)
            status_text = st.empty()
            execution_results = []
            
            for idx, result in enumerate(confirmed_results):
                progress = (idx + 1) / len(confirmed_results)
                progress_bar.progress(progress)
                status_text.text(f"整理中... {idx + 1}/{len(confirmed_results)}")
                
                try:
                    # 更新中繼資料
                    storage.update_file_metadata(result['file_id'], {
                        'standard_date': result['standard_date'],
                        'main_topic': result['main_topic'],
                        'summary': result.get('summary', ''),
                        'content': result['metadata'].get('extracted_text', ''),
                        'is_scanned': result.get('is_scanned', False)
                    })
                    
                    # 添加標籤
                    storage.add_tags_to_file(result['file_id'], result['tag_scores'])
                    
                    # 執行最終整理
                    final_path = storage.finalize_organization(
                        result['file_id'],
                        result['standard_date'],
                        result['main_topic'],
                        result['original_name']
                    )
                    
                    execution_results.append({
                        'original_name': result['original_name'],
                        'new_path': final_path,
                        'status': 'SUCCESS'
                    })
                    
                except Exception as e:
                    logger.error(f"整理失敗 ({result['file_id']}): {e}")
                    execution_results.append({
                        'original_name': result['original_name'],
                        'error': str(e),
                        'status': 'FAILED'
                    })
            
            progress_bar.progress(1.0)
            status_text.text("✅ 整理完成！")
            
            st.session_state.execution_results = execution_results
            st.session_state.analysis_results = []
            st.session_state.confirmed_results = []
            
            for res in execution_results:
                if res['status'] == 'SUCCESS':
                    st.success(f"✅ {res['original_name']} -> {res['new_path']}")
                else:
                    st.error(f"❌ {res['original_name']} 失敗: {res['error']}")
    else:
        st.info("請先在「預覽與確認」頁籤確認檔案")

with tab4:
    st.header("步驟 4：全文檢索")
    
    search_query = st.text_input("輸入搜尋關鍵字", placeholder="例如：軟體開發、統編 12345678")
    
    if search_query:
        with st.spinner("搜尋中..."):
            try:
                # 【FTS 安全化】轉義邏輯已移至 Storage 層，UI 直接傳入原始字串
                results = storage.search_content(search_query)
                
                if results:
                    st.success(f"✅ 找到 {len(results)} 個相關檔案")
                    
                    for result in results:
                        with st.expander(f"📄 {result['original_name']} ({result['standard_date']})"):
                            st.write(f"**主題**: {result['main_topic']}")
                            st.write(f"**路徑**: {result['final_path']}")
                            st.markdown(f"**內容片段**: ...{result['snippet']}...")
                            if result['final_path'] and os.path.exists(result['final_path']):
                                with open(result['final_path'], "rb") as f:
                                    st.download_button(
                                        "下載檔案",
                                        f,
                                        file_name=os.path.basename(result['final_path']),
                                        key=f"dl_{result['file_id']}"
                                    )
                else:
                    st.info("🔍 找不到相關檔案，請嘗試其他關鍵字")
            except Exception as e:
                logger.error(f"搜尋失敗: {e}")
                st.error(f"❌ 搜尋失敗: {e}")
    else:
        st.info("🔍 輸入搜尋關鍵字，支援中文、英文及數字")

with tab5:
    st.header("步驟 5：查看紀錄")
    
    records = storage.get_all_records()
    if records:
        df = pd.DataFrame(records)
        # 整理顯示欄位
        display_df = df[['file_id', 'original_name', 'standard_date', 'main_topic', 'all_tags', 'status', 'created_at']]
        st.dataframe(display_df, use_container_width=True)
        
        # 統計圖表
        st.subheader("統計分析")
        col1, col2 = st.columns(2)
        with col1:
            st.write("**主題分佈**")
            topic_counts = df['main_topic'].value_counts()
            st.bar_chart(topic_counts)
        with col2:
            st.write("**處理狀態**")
            status_counts = df['status'].value_counts()
            # 【v2.7 修正】使用 matplotlib 繪製圓餅圖，修復 st.pie_chart() 錯誤
            fig, ax = plt.subplots()
            status_counts.plot.pie(ax=ax, autopct='%1.1f%%', startangle=90)
            ax.set_ylabel("")
            st.pyplot(fig)
    else:
        st.info("目前尚無處理紀錄")

st.divider()
st.caption("智慧檔案整理助理 v2.7.1 Steel-Fortified Hotfix | Powered by Python & Streamlit")
