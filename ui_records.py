from __future__ import annotations

import logging

import streamlit as st

from services import reclassify_record
from ui_common import UIContext, handle_ui_exception

logger = logging.getLogger(__name__)


def render_records(context: UIContext) -> None:
    st.header("整理紀錄")
    try:
        records = context.storage.get_all_records()
    except Exception as exc:
        logger.exception("get_all_records failed")
        handle_ui_exception("讀取整理紀錄失敗。", exc)
        return

    if not records:
        st.info("目前沒有整理紀錄。")
        return

    if context.pandas is not None:
        df = context.pandas.DataFrame(records)
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
        st.dataframe(df[[col for col in cols if col in df.columns]], use_container_width=True)
    else:
        st.dataframe(records, use_container_width=True)

    st.subheader("維護工具")
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("刷新檔案位置", key="refresh_locations"):
            try:
                with st.spinner("刷新中..."):
                    result = context.storage.refresh_file_locations(fix_moving=True)
                if result.get("success"):
                    st.success(str(result.get("summary") or "完成"))
                else:
                    st.error(str(result.get("error") or "失敗"))
            except Exception as exc:
                handle_ui_exception("刷新檔案位置失敗。", exc)

    with col_b:
        if st.button("重建搜尋索引", key="rebuild_fts"):
            try:
                with st.spinner("重建中..."):
                    result = context.storage.reconcile_fts_rows()
                if result.get("success"):
                    st.success("FTS 索引重建完成")
                else:
                    st.error(str(result.get("error") or "失敗"))
            except Exception as exc:
                handle_ui_exception("重建搜尋索引失敗。", exc)

    with col_c:
        st.caption("可針對既有記錄做修復或重新分類。")

    file_id_options = [record.get("file_id") for record in records if record.get("file_id") is not None]
    if file_id_options:
        selected_file_id = st.selectbox("選擇 file_id", file_id_options, index=0, key="reclassify_file_id")
        if st.button("重新分類", key="do_reclassify"):
            try:
                with st.spinner("重新分類中..."):
                    main_topic = reclassify_record(
                        storage=context.storage,
                        processor=context.processor,
                        file_id=int(selected_file_id),
                        processing_options=st.session_state.get("processing_options"),
                    )
                st.success(f"最新主題：{main_topic}")
            except FileNotFoundError:
                st.error("找不到原始檔案，請先確認實體檔案是否仍存在。")
            except Exception as exc:
                logger.exception("reclassify_record failed")
                handle_ui_exception("重新分類失敗。", exc)

    if context.pandas is None:
        return

    df = context.pandas.DataFrame(records)
    st.subheader("統計")
    col1, col2 = st.columns(2)
    with col1:
        if "main_topic" in df.columns:
            counts = (
                df["main_topic"].dropna().astype(str).replace("", context.pandas.NA).dropna().value_counts()
            )
            if not counts.empty:
                st.bar_chart(counts)
    with col2:
        if "status" in df.columns:
            counts = (
                df["status"].dropna().astype(str).replace("", context.pandas.NA).dropna().value_counts()
            )
            if counts.empty:
                return
            if context.plt is None:
                st.bar_chart(counts)
            else:
                fig, ax = context.plt.subplots()
                counts.plot.pie(ax=ax, autopct="%1.1f%%", startangle=90)
                ax.set_ylabel("")
                st.pyplot(fig)
                context.plt.close(fig)
