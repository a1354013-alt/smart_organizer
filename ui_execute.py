from __future__ import annotations

import logging

import streamlit as st

from services import AnalysisResult, finalize_batch
from ui_common import UIContext, handle_ui_exception
from ui_state import reset_review_state

logger = logging.getLogger(__name__)


def render_execute(context: UIContext) -> None:
    st.header("Execute Organization")
    confirmed_results = st.session_state.get("confirmed_results")
    if not confirmed_results:
        st.info("Confirm reviewed items first, then run the organization step here.")
        return
    if not st.button("Organize confirmed files", key="execute_button"):
        return

    progress_bar = st.progress(0)
    status_text = st.empty()

    def on_execute_progress(index: int, total: int, result: AnalysisResult) -> None:
        progress_bar.progress(index / total)
        status_text.text(f"Organizing {index}/{total}: {result.original_name}")

    try:
        execution_results = finalize_batch(
            confirmed_results,
            storage=context.storage,
            progress_callback=on_execute_progress,
        )
        progress_bar.progress(1.0)
        status_text.text("Organization completed.")
        st.session_state.execution_results = execution_results
        st.session_state.analysis_results = []
        st.session_state.confirmed_results = []
        reset_review_state()

        for result in execution_results:
            if result.status == "SUCCESS":
                st.success(f"{result.original_name} -> {result.new_path}")
            else:
                detail = f": {result.error_message}" if result.error_message else ""
                st.error(f"{result.original_name} failed{detail}")
    except Exception as exc:
        logger.exception("render_execute failed")
        handle_ui_exception("Execution failed.", exc)
