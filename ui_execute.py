from __future__ import annotations

import logging
from collections.abc import Sequence

import streamlit as st

from i18n import t
from services import AnalysisResult, ExecutionResult, finalize_batch
from ui_common import UIContext, handle_ui_exception, safe_display_text
from ui_state import reset_review_state

logger = logging.getLogger(__name__)


def _retryable_confirmed_results(
    confirmed_results: Sequence[AnalysisResult],
    execution_results: Sequence[ExecutionResult],
) -> list[AnalysisResult]:
    retryable: list[AnalysisResult] = []
    confirmed_by_id = {result.file_id: result for result in confirmed_results}
    for confirmed_result, execution_result in zip(confirmed_results, execution_results, strict=False):
        if execution_result.status != "FAILED":
            continue
        if execution_result.file_id is not None and execution_result.file_id in confirmed_by_id:
            retryable.append(confirmed_by_id[int(execution_result.file_id)])
            continue
        retryable.append(confirmed_result)
    return retryable


def render_execute(context: UIContext) -> None:
    st.header(t("execute.title"))
    markdown = getattr(st, "markdown", None)
    if callable(markdown):
        markdown(t("execute.description"))
    confirmed_results = st.session_state.get("confirmed_results")
    if not confirmed_results:
        st.info(t("execute.empty"))
        return
    if not st.button(t("execute.button"), key="execute_button"):
        return

    progress_bar = st.progress(0)
    status_text = st.empty()

    def on_execute_progress(index: int, total: int, result: AnalysisResult) -> None:
        progress_bar.progress(index / total)
        status_text.text(t("execute.progress", index=index, total=total, name=safe_display_text(result.original_name)))

    try:
        execution_results = finalize_batch(
            confirmed_results,
            storage=context.storage,
            progress_callback=on_execute_progress,
        )
        confirmed_result_list = list(confirmed_results)
        retryable_results = _retryable_confirmed_results(confirmed_result_list, execution_results)
        success_count = sum(1 for result in execution_results if result.status == "SUCCESS")
        failed_count = sum(1 for result in execution_results if result.status == "FAILED")
        progress_bar.progress(1.0)
        status_text.text(
            t("execute.complete") if failed_count == 0 else t("execute.complete_with_retryable_failures")
        )
        st.session_state.execution_results = execution_results
        st.session_state.analysis_results = []
        st.session_state.confirmed_results = retryable_results
        reset_review_state()

        if failed_count == 0:
            st.success(t("execute.success", count=success_count))
        else:
            st.warning(t("execute.partial_success", success_count=success_count, failed_count=failed_count))

        for result in execution_results:
            if result.status == "SUCCESS":
                st.success(
                    t(
                        "execute.item_success",
                        name=safe_display_text(result.original_name),
                        path=safe_display_text(result.new_path),
                    )
                )
            else:
                detail = f": {safe_display_text(result.error_message)}" if result.error_message else ""
                st.error(t("execute.item_failed", name=safe_display_text(result.original_name), detail=detail))
        if retryable_results:
            st.info(
                t(
                    "execute.retry_ready",
                    names=", ".join(safe_display_text(result.original_name) for result in retryable_results),
                )
            )
    except Exception as exc:
        logger.exception("render_execute failed")
        handle_ui_exception(t("execute.failed"), exc)
