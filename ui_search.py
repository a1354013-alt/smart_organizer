from __future__ import annotations

import logging
import os

import streamlit as st

from storage import SearchContentError
from ui_common import UIContext, handle_ui_exception

logger = logging.getLogger(__name__)


def render_search(context: UIContext) -> None:
    st.header("搜尋")
    search_query = st.text_input("輸入關鍵字", placeholder="例如：發票、截圖、專案名稱")
    if not search_query:
        st.info("可搜尋檔名、摘要、分類與內容片段。")
        return

    with st.spinner("搜尋中..."):
        try:
            results = context.storage.search_content(search_query)
            if not results:
                st.info("找不到符合結果。")
                return
            st.success(f"找到 {len(results)} 筆結果")
            for result in results:
                with st.expander(f"{result['original_name']} ({result['standard_date']})"):
                    st.write(f"**主題**: {result['main_topic']}")
                    st.write(f"**路徑**: {result['final_path']}")
                    if result.get("all_tags"):
                        st.write(f"**標籤**: {result['all_tags']}")
                    st.markdown(f"**片段**: ...{result.get('snippet', '')}...")
                    if result.get("final_path") and context.storage.path_exists(result["final_path"]):
                        with open(result["final_path"], "rb") as handle:
                            st.download_button(
                                "下載檔案",
                                handle,
                                file_name=os.path.basename(result["final_path"]),
                                key=f"dl_{result['file_id']}",
                            )
        except SearchContentError:
            logger.exception("search_content failed")
            st.error("搜尋索引異常，請先到整理紀錄頁嘗試重建索引。")
        except Exception as exc:
            logger.exception("render_search failed")
            handle_ui_exception("搜尋失敗。", exc)
