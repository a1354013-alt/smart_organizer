from __future__ import annotations

import logging

import streamlit as st

from core import DOCUMENT_TAGS, PHOTO_TAGS, VIDEO_TAGS
from services import (
    AnalysisResult,
    apply_manual_topic_override,
    build_confirmed_results,
    generate_summary_suggestion,
)
from ui_common import UIContext, handle_ui_exception, is_debug
from ui_renderers import render_video_details

logger = logging.getLogger(__name__)


def _tag_options_for(file_type: str) -> list[str]:
    if file_type == "document":
        return list(DOCUMENT_TAGS)
    if file_type == "photo":
        return list(PHOTO_TAGS)
    if file_type == "video":
        return list(VIDEO_TAGS)
    return list(DOCUMENT_TAGS)


def render_review(context: UIContext) -> None:
    st.header("預覽確認")
    analysis_results_raw = st.session_state.get("analysis_results")
    if not analysis_results_raw:
        st.info("請先到「上傳分析」完成分析。")
        return
    if not isinstance(analysis_results_raw, list):
        st.error("分析結果格式不正確。")
        if is_debug():
            st.json({"type": str(type(analysis_results_raw))})
        return

    analysis_results: list[AnalysisResult] = analysis_results_raw
    st.markdown("逐筆確認主題、摘要與預覽內容，沒問題後再送往整理流程。")
    selected_topics: dict[int, str] = {}

    for idx, result in enumerate(analysis_results):
        with st.expander(f"{idx + 1}. {result.original_name}", expanded=(idx == 0)):
            col1, col2 = st.columns([1, 2])
            with col1:
                st.subheader("預覽")
                if result.preview_path and context.storage.path_exists(result.preview_path):
                    try:
                        st.image(str(result.preview_path), use_container_width=True)
                    except Exception as exc:
                        if is_debug():
                            st.exception(exc)
                        else:
                            st.info("預覽載入失敗。")
                elif result.file_type == "video":
                    st.warning("目前沒有可用的影片縮圖。")
                else:
                    st.info("沒有可用預覽。")

            with col2:
                st.subheader("分析資訊")
                st.write(f"**檔名**: {result.original_name}")
                st.write(f"**類型**: {result.file_type}")
                st.write(f"**日期**: {result.standard_date}")
                if str(getattr(result, "analysis_status", "OK") or "OK") in {"WARNING", "PARTIAL"}:
                    st.warning("此檔案有部分分析步驟降級或失敗。")
                    if getattr(result, "last_error", None):
                        st.caption(f"last_error: {result.last_error}")
                    if is_debug() and getattr(result, "step_timings", None):
                        st.caption("step_timings")
                        st.json(result.step_timings or {})

                if result.file_type == "video":
                    render_video_details(result.metadata or {})

                if result.is_scanned:
                    st.warning("此文件可能是掃描檔，已依 OCR/抽取結果進行處理。")
                notes = (result.metadata or {}).get("notes")
                if notes:
                    note_lines = notes if isinstance(notes, list) else [str(notes)]
                    st.info("處理備註\n- " + "\n- ".join(map(str, note_lines)))

                tag_options = _tag_options_for(result.file_type) or ["Unclassified"]
                current_index = tag_options.index(result.main_topic) if result.main_topic in tag_options else 0
                new_topic = st.selectbox(
                    "主題",
                    tag_options,
                    index=current_index,
                    key=f"topic_{idx}_{result.file_id}",
                )
                selected_topics[result.file_id] = new_topic

                computed = result
                try:
                    computed = apply_manual_topic_override(
                        result,
                        processor=context.processor,
                        chosen_topic=new_topic,
                        summary=st.session_state.review_summaries.get(result.file_id),
                    )
                    st.caption("分類理由")
                    st.code(str(computed.classification_reason or ""))
                    st.caption("最終決策")
                    st.code(str(computed.final_decision_reason or ""))
                except Exception as exc:
                    logger.exception("manual override preview failed")
                    handle_ui_exception("主題預覽更新失敗。", exc)

                if st.button("產生 AI 摘要", key=f"summary_{idx}_{result.file_id}"):
                    if not st.session_state.get("ai_enabled"):
                        st.warning("請先在側邊欄啟用 AI 摘要。")
                    else:
                        try:
                            suggestion = generate_summary_suggestion(computed, processor=context.processor)
                            st.session_state.review_summaries[result.file_id] = suggestion.summary
                            st.info(f"摘要：{suggestion.summary}")
                            if suggestion.llm_tags:
                                st.caption(f"AI tags: {', '.join(suggestion.llm_tags)}")
                        except Exception as exc:
                            logger.exception("summary generation failed")
                            handle_ui_exception("AI 摘要產生失敗。", exc)

                saved_summary = st.session_state.review_summaries.get(result.file_id) or result.summary
                if saved_summary:
                    st.write(f"**摘要**: {saved_summary}")

    if st.button("確認無誤，進行整理", key="confirm_button"):
        try:
            st.session_state.confirmed_results = build_confirmed_results(
                analysis_results,
                processor=context.processor,
                selected_topics=selected_topics,
                summaries=st.session_state.review_summaries,
            )
            st.success("已建立確認結果，現在可前往「執行整理」。")
        except Exception as exc:
            logger.exception("build_confirmed_results failed")
            handle_ui_exception("確認流程失敗。", exc)
