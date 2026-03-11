import streamlit as st
import os
import tempfile
import pandas as pd
from core import FileProcessor, DOCUMENT_TAGS, PHOTO_TAGS
from storage import StorageManager

# 配置
DB_PATH = "/home/ubuntu/smart_organizer/smart_organizer.db"
REPO_ROOT = "/home/ubuntu/smart_organizer/repo"
UPLOAD_DIR = "/home/ubuntu/smart_organizer/uploads"

# 初始化
processor = FileProcessor()
storage = StorageManager(DB_PATH, REPO_ROOT)

st.set_page_config(page_title="智慧檔案整理助理", layout="wide")
st.title("📁 智慧檔案整理助理 (V2 終極版)")
st.markdown("**AI 驅動的智慧分類、預覽與全文檢索 - 企業級檔案管理**")

# Sidebar 配置
st.sidebar.header("⚙️ 設定")
repo_path = st.sidebar.text_input("儲存庫路徑", REPO_ROOT)
if repo_path != REPO_ROOT:
    REPO_ROOT = repo_path
    storage = StorageManager(DB_PATH, REPO_ROOT)

# 主要流程
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
                
                temp_path = os.path.join(UPLOAD_DIR, uploaded_file.name)
                with open(temp_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                
                file_hash = processor.get_file_hash(temp_path)
                
                duplicate_check = storage.check_duplicate(file_hash)
                if duplicate_check:
                    duplicates.append({
                        'filename': uploaded_file.name,
                        'existing_path': duplicate_check[1]
                    })
                    continue
                
                metadata = processor.extract_metadata(temp_path)
                main_topic, tag_scores = processor.classify_multi_tag(metadata, uploaded_file.name)
                
                if metadata['standard_date'] is None:
                    metadata['standard_date'] = 'UnknownDate'
                
                file_id = storage.create_pending_record({
                    'original_name': uploaded_file.name,
                    'file_hash': file_hash,
                    'file_type': metadata['file_type']
                })
                
                if file_id:
                    analysis_results.append({
                        'file_id': file_id,
                        'temp_path': temp_path,
                        'original_name': uploaded_file.name,
                        'file_hash': file_hash,
                        'file_type': metadata['file_type'],
                        'standard_date': metadata['standard_date'],
                        'main_topic': main_topic,
                        'tag_scores': tag_scores,
                        'metadata': metadata,
                        'preview_path': metadata.get('preview_path')
                    })
            
            progress_bar.progress(1.0)
            status_text.text("✅ 分析完成！")
            
            if duplicates:
                st.warning(f"⚠️ 發現 {len(duplicates)} 個重複檔案，已跳過")
                for dup in duplicates:
                    st.write(f"  - {dup['filename']}")
            
            st.session_state.analysis_results = analysis_results
            st.session_state.analysis_complete = True
            
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
                
                # 左側：預覽圖
                with col1:
                    st.subheader("預覽")
                    if result['preview_path'] and os.path.exists(result['preview_path']):
                        try:
                            from PIL import Image
                            img = Image.open(result['preview_path'])
                            st.image(img, use_column_width=True)
                        except:
                            st.info("無法顯示預覽")
                    else:
                        st.info("無預覽圖")
                
                # 右側：詳細資訊與編輯
                with col2:
                    st.subheader("詳細資訊")
                    st.write(f"**檔名**: {result['original_name']}")
                    st.write(f"**類型**: {result['file_type']}")
                    st.write(f"**日期**: {result['standard_date']}")
                    
                    # 標籤顯示
                    st.write("**建議標籤**:")
                    tag_str = ", ".join([f"{tag}({score:.0%})" for tag, score in result['tag_scores'].items()])
                    st.write(tag_str)
                    
                    # 主題選擇
                    tag_options = DOCUMENT_TAGS if result['file_type'] == 'document' else PHOTO_TAGS
                    new_topic = st.selectbox(
                        "選擇主題",
                        tag_options,
                        index=tag_options.index(result['main_topic']) if result['main_topic'] in tag_options else 0,
                        key=f"topic_{idx}"
                    )
                    result['main_topic'] = new_topic
                    
                    # LLM 摘要 (可選)
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
            st.session_state.ready_to_organize = True
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
                    storage.update_file_metadata(result['file_id'], {
                        'standard_date': result['standard_date'],
                        'main_topic': result['main_topic'],
                        'summary': result.get('summary', ''),
                        'content': result['metadata'].get('extracted_text', '')
                    })
                    
                    storage.add_tags_to_file(result['file_id'], result['tag_scores'])
                    
                    new_path = storage.finalize_organization(
                        result['file_id'],
                        result['temp_path'],
                        result['standard_date'],
                        result['main_topic'],
                        result['original_name']
                    )
                    
                    execution_results.append({
                        'original_name': result['original_name'],
                        'new_path': new_path,
                        'status': 'SUCCESS'
                    })
                    
                except Exception as e:
                    execution_results.append({
                        'original_name': result['original_name'],
                        'error': str(e),
                        'status': 'FAILED'
                    })
            
            progress_bar.progress(1.0)
            status_text.text("✅ 整理完成！")
            
            st.success(f"🎉 成功整理 {len([r for r in execution_results if r['status'] == 'SUCCESS'])} 個檔案")
            
            df_execution = pd.DataFrame(execution_results)
            st.dataframe(df_execution, use_container_width=True)
            
            del st.session_state.analysis_results
            del st.session_state.confirmed_results
            del st.session_state.ready_to_organize
    else:
        st.info("請先在「預覽與確認」頁籤確認檔案")

with tab4:
    st.header("步驟 4：全文檢索")
    st.markdown("在已整理的檔案中搜尋內容")
    
    search_query = st.text_input("輸入搜尋關鍵字", placeholder="例如：軟體開發、統編 12345678")
    
    if search_query:
        with st.spinner("搜尋中..."):
            results = storage.search_content(search_query)
        
        if results:
            st.success(f"✅ 找到 {len(results)} 個相關檔案")
            
            for result in results:
                with st.expander(f"📄 {result['original_name']} ({result['standard_date']})"):
                    st.write(f"**主題**: {result['main_topic']}")
                    st.write(f"**摘要**: {result.get('summary', '無摘要')}")
                    if result.get('snippet'):
                        st.write(f"**相關片段**: ...{result['snippet']}...")
                    st.write(f"**路徑**: {result['new_path']}")
        else:
            st.warning("未找到相關檔案")

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
            unique_dates = df_all['standard_date'].nunique()
            st.metric("日期種類", unique_dates)
        
        st.subheader("主題分佈")
        topic_counts = df_all['main_topic'].value_counts()
        st.bar_chart(topic_counts)
        
        st.subheader("詳細紀錄")
        display_cols = ['original_name', 'standard_date', 'main_topic', 'file_type', 'status', 'summary']
        df_display = df_all[display_cols].copy()
        df_display.columns = ['檔名', '日期', '主題', '類型', '狀態', '摘要']
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
**🚀 V2 終極版功能亮點：**
- ✅ **視覺化預覽**：PDF 自動轉圖片、照片直接預覽
- ✅ **全文檢索**：搜尋檔案內容，秒級找到相關檔案
- ✅ **LLM 智慧摘要**：AI 自動生成文件摘要與建議標籤
- ✅ **多標籤支援**：每個檔案可擁有多個主題標籤
- ✅ **狀態追蹤**：完整的生命週期管理
""")
