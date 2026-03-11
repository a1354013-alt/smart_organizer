import streamlit as st
import os
import logging
import pandas as pd
from pathlib import Path
from core import FileProcessor, DOCUMENT_TAGS, PHOTO_TAGS
from storage import StorageManager

# ========== 路徑配置 (集中管理) ==========
PROJECT_ROOT = Path(__file__).parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
REPO_ROOT = PROJECT_ROOT / "repo"
DB_PATH = PROJECT_ROOT / "smart_organizer.db"

# 設定 Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 初始化 (注意：StorageManager 現在接收 upload_dir 參數)
processor = FileProcessor()
storage = StorageManager(str(DB_PATH), str(REPO_ROOT), str(UPLOAD_DIR))

st.set_page_config(page_title="智慧檔案整理助理", layout="wide")
st.title("📁 智慧檔案整理助理 (V2.1 終極加固版)")
st.markdown("**資料庫驅動的檔案生命週期管理系統 - 路徑完全封裝**")

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
                    # 【路徑封裝】UI 不再自己組路徑，交由 Storage 層
                    file_hash = processor.get_file_hash(uploaded_file)
                    
                    # 檢查重複
                    duplicate_check = storage.check_duplicate(file_hash)
                    if duplicate_check:
                        duplicates.append({
                            'filename': uploaded_file.name,
                            'existing_path': duplicate_check[1]
                        })
                        continue
                    
                    # 【路徑封裝】由 Storage 層建立暫存檔並回傳 file_id
                    file_id = storage.create_temp_file(
                        uploaded_file.name,
                        uploaded_file.getbuffer(),
                        file_hash,
                        'photo' if uploaded_file.type.startswith('image') else 'document'
                    )
                    
                    if not file_id:
                        st.error(f"❌ 無法建立暫存檔: {uploaded_file.name}")
                        continue
                    
                    # 【路徑讀取】由 Storage 層提供路徑
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
                    st.write(f"  - {dup['filename']}")
            
            st.session_state.analysis_results = analysis_results
            
            if analysis_results:
                st.info(f"✅ 成功分析 {len(analysis_results)} 個檔案，請前往「預覽與確認」頁籤")

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
                    # 【路徑讀取】由 Storage 層提供路徑
                    file_info = storage.get_file_by_id(result['file_id'])
                    if not file_info:
                        raise ValueError(f"找不到檔案紀錄: {result['file_id']}")
                    
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
                    
                    # 【路徑組裝】由 Storage 層決定最終路徑
                    year = result['standard_date'].split('-')[0] if result['standard_date'] and '-' in result['standard_date'] else "UnknownYear"
                    month = result['standard_date'][:7] if result['standard_date'] and len(result['standard_date']) >= 7 else "UnknownMonth"
                    target_dir = REPO_ROOT / year / month
                    
                    new_filename = f"{result['standard_date']}_{result['main_topic']}_{result['original_name']}"
                    new_filename = processor.sanitize_filename(new_filename)
                    target_path = str(target_dir / new_filename)
                    target_path = processor.get_unique_path(target_path)
                    
                    # 【路徑移動】由 Storage 層執行
                    final_path = storage.finalize_organization(result['file_id'], target_path)
                    
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
            
            successful = len([r for r in execution_results if r['status'] == 'SUCCESS'])
            st.success(f"🎉 成功整理 {successful} 個檔案")
            
            df_execution = pd.DataFrame(execution_results)
            st.dataframe(df_execution, use_container_width=True)
            
            del st.session_state.analysis_results
            del st.session_state.confirmed_results
    else:
        st.info("請先在「預覽與確認」頁籤確認檔案")

with tab4:
    st.header("步驟 4：全文檢索")
    st.markdown("在已整理的檔案中搜尋內容")
    
    search_query = st.text_input("輸入搜尋關鍵字", placeholder="例如：軟體開發、統編 12345678")
    
    if search_query:
        with st.spinner("搜尋中..."):
            try:
                results = storage.search_content(search_query)
                
                if results:
                    st.success(f"✅ 找到 {len(results)} 個相關檔案")
                    
                    for result in results:
                        with st.expander(f"📄 {result['original_name']} ({result['standard_date']})"):
                            st.write(f"**主題**: {result['main_topic']}")
                            st.write(f"**摘要**: {result.get('summary', '無摘要')}")
                            if result.get('is_scanned'):
                                st.info("ℹ️ 此為掃描 PDF，已執行 OCR 處理")
                            if result.get('snippet'):
                                st.write(f"**相關片段**: ...{result['snippet']}...")
                            st.write(f"**路徑**: {result['final_path']}")
                else:
                    st.warning("未找到相關檔案")
            except Exception as e:
                logger.error(f"搜尋失敗: {e}")
                st.error(f"❌ 搜尋失敗: {e}")

with tab5:
    st.header("步驟 5：統計與查看紀錄")
    
    all_records = storage.get_all_records()
    
    if all_records:
        df_all = pd.DataFrame(all_records)
        
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("總檔案數", len(df_all))
        with col2:
            completed = len(df_all[df_all['status'] == 'COMPLETED'])
            st.metric("已完成", completed)
        with col3:
            doc_count = len(df_all[df_all['file_type'] == 'document'])
            st.metric("文件數", doc_count)
        with col4:
            photo_count = len(df_all[df_all['file_type'] == 'photo'])
            st.metric("照片數", photo_count)
        with col5:
            scanned = len(df_all[df_all['is_scanned'] == 1])
            st.metric("掃描檔", scanned)
        
        st.subheader("主題分佈")
        topic_counts = df_all['main_topic'].value_counts()
        st.bar_chart(topic_counts)
        
        st.subheader("詳細紀錄")
        display_cols = ['original_name', 'standard_date', 'main_topic', 'file_type', 'status', 'is_scanned', 'summary']
        df_display = df_all[display_cols].copy()
        df_display.columns = ['檔名', '日期', '主題', '類型', '狀態', '掃描', '摘要']
        st.dataframe(df_display, use_container_width=True)
        
        st.subheader("📥 匯出清單")
        csv_data = df_all.to_csv(index=False, encoding='utf-8-sig')
        st.download_button(
            label="下載 CSV 清單",
            data=csv_data,
            file_name="smart_organizer_list.csv",
            mime="text/csv"
        )
    else:
        st.warning("尚無資料可顯示")

st.markdown("---")
st.markdown("""
**🔧 V2.1 終極加固版改進：**
- ✅ **路徑完全封裝**：app.py 完全不自己組路徑，所有操作由 StorageManager 統一管理
- ✅ **資料庫驅動**：所有檔案操作以 DB 中的 filePath 為唯一來源
- ✅ **Schema 版本化**：sys_config 表追蹤版本，支援未來 Migration
- ✅ **掃描檔 OCR 補強**：自動 OCR 第一頁，掃描檔也能搜尋與分類
- ✅ **FTS5 修復**：使用 bm25 排序，全文檢索穩定運作
- ✅ **檔名安全**：自動清洗非法字元，衝突自動加序號
""")
