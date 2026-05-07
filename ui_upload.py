from __future__ import annotations

import logging

import streamlit as st

from services import UploadedFileData, analyze_upload_batch
from supported_formats import SUPPORTED_UPLOAD_EXTENSIONS, supported_upload_extensions_label
from ui_common import UIContext, build_uploaded_file_batch, handle_ui_exception
from ui_state import reset_review_state

logger = logging.getLogger(__name__)


def get_supported_upload_types() -> list[str]:
    return list(SUPPORTED_UPLOAD_EXTENSIONS)


def get_supported_upload_caption() -> str:
    return supported_upload_extensions_label()


def render_upload(context: UIContext) -> None:
    st.header("上傳分析")
    st.markdown("可一次上傳多個 PDF、圖片與影片檔，先完成分析再進入確認流程。")
    st.caption(f"支援格式：{get_supported_upload_caption()}")

    uploaded_files = st.file_uploader(
        "選擇檔案",
        type=get_supported_upload_types(),
        accept_multiple_files=True,
    )
    if not uploaded_files:
        st.info("請先選擇要分析的檔案。")
        return

    st.success(f"已選擇 {len(uploaded_files)} 個檔案")
    if not st.button("開始分析", key="analyze_button"):
        return

    reset_review_state()
    progress_bar = st.progress(0)
    status_text = st.empty()
    uploaded_batch = build_uploaded_file_batch(uploaded_files)

    def on_progress(index: int, total: int, uploaded: UploadedFileData) -> None:
        progress_bar.progress(index / total)
        status_text.text(f"分析中 {index}/{total} - {uploaded.name}")
        st.session_state.current_processing_file = uploaded.name

    try:
        outcome = analyze_upload_batch(
            uploaded_batch,
            processor=context.processor,
            storage=context.storage,
            processing_options=st.session_state.get("processing_options"),
            progress_callback=on_progress,
        )
        progress_bar.progress(1.0)
        status_text.text("分析完成")
        st.session_state.analysis_results = outcome.results

        for error in outcome.errors:
            st.error(error)
        if outcome.duplicates:
            st.warning(f"有 {len(outcome.duplicates)} 個重複檔案")
            for duplicate in outcome.duplicates:
                st.info(duplicate.display)
        if outcome.results:
            st.success(f"已完成 {len(outcome.results)} 個檔案分析，請到「預覽確認」查看。")
        else:
            st.warning("這次沒有產生可確認的分析結果。")
    except Exception as exc:
        logger.exception("render_upload failed")
        handle_ui_exception("上傳分析失敗。", exc)
