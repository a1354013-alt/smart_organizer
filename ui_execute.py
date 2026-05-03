from __future__ import annotations

import logging

import streamlit as st

from services import AnalysisResult, finalize_batch
from ui_common import UIContext, handle_ui_exception
from ui_state import reset_review_state

logger = logging.getLogger(__name__)


def render_execute(context: UIContext) -> None:
    st.header("執行整理")
    confirmed_results = st.session_state.get("confirmed_results")
    if not confirmed_results:
        st.info("請先在「預覽確認」完成確認。")
        return
    if not st.button("開始整理", key="execute_button"):
        return

    progress_bar = st.progress(0)
    status_text = st.empty()

    def on_execute_progress(index: int, total: int, result: AnalysisResult) -> None:
        progress_bar.progress(index / total)
        status_text.text(f"整理中 {index}/{total} - {result.original_name}")

    try:
        execution_results = finalize_batch(
            confirmed_results,
            storage=context.storage,
            progress_callback=on_execute_progress,
        )
        progress_bar.progress(1.0)
        status_text.text("整理完成")
        st.session_state.execution_results = execution_results
        st.session_state.analysis_results = []
        st.session_state.confirmed_results = []
        reset_review_state()

        for result in execution_results:
            if result.status == "SUCCESS":
                st.success(f"{result.original_name} -> {result.new_path}")
            else:
                st.error(f"{result.original_name} 整理失敗")
    except Exception as exc:
        logger.exception("render_execute failed")
        handle_ui_exception("執行整理失敗。", exc)
