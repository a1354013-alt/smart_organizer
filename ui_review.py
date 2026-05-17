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
from ui_common import UIContext, handle_ui_exception, is_debug, safe_display_text
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
    st.header("Review upload analysis")
    analysis_results_raw = st.session_state.get("analysis_results")
    if not analysis_results_raw:
        st.info("Run advanced upload analysis first, then review the results here.")
        return
    if not isinstance(analysis_results_raw, list):
        st.error("Analysis results have an unexpected format.")
        if is_debug():
            st.json({"type": str(type(analysis_results_raw))})
        return

    analysis_results: list[AnalysisResult] = analysis_results_raw
    st.markdown("Review topics, summaries, and previews before sending files to the organization step.")
    selected_topics: dict[int, str] = {}

    for idx, result in enumerate(analysis_results):
        safe_name = safe_display_text(result.original_name)
        with st.expander(f"{idx + 1}. {safe_name}", expanded=(idx == 0)):
            col1, col2 = st.columns([1, 2])
            with col1:
                st.subheader("Preview")
                if result.preview_path and context.storage.path_exists(result.preview_path):
                    try:
                        st.image(str(result.preview_path), use_container_width=True)
                    except Exception as exc:
                        if is_debug():
                            st.exception(exc)
                        else:
                            st.info("Preview could not be loaded.")
                elif result.file_type == "video":
                    st.warning("No video thumbnail is currently available.")
                else:
                    st.info("No preview is available.")

            with col2:
                st.subheader("Analysis")
                st.write(f"**Filename**: {safe_name}")
                st.write(f"**Type**: {safe_display_text(result.file_type)}")
                st.write(f"**Date**: {safe_display_text(result.standard_date)}")
                if str(getattr(result, "analysis_status", "OK") or "OK") in {"WARNING", "PARTIAL"}:
                    st.warning("Some analysis steps were degraded or fell back safely.")
                    if getattr(result, "last_error", None):
                        st.caption(f"last_error: {safe_display_text(result.last_error)}")
                    if is_debug() and getattr(result, "step_timings", None):
                        st.caption("step_timings")
                        st.json(result.step_timings or {})

                if result.file_type == "video":
                    render_video_details(result.metadata or {})

                if result.is_scanned:
                    st.warning("This document may be scanned; OCR or fallback extraction was used.")
                notes = (result.metadata or {}).get("notes")
                if notes:
                    note_lines = notes if isinstance(notes, list) else [str(notes)]
                    st.info("Processing notes\n- " + "\n- ".join(safe_display_text(note) for note in note_lines))

                tag_options = _tag_options_for(result.file_type) or ["Unclassified"]
                current_index = tag_options.index(result.main_topic) if result.main_topic in tag_options else 0
                new_topic = st.selectbox(
                    "Topic",
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
                    st.caption("Classification reason")
                    st.code(str(computed.classification_reason or ""))
                    st.caption("Decision reason")
                    st.code(str(computed.final_decision_reason or ""))
                except Exception as exc:
                    logger.exception("manual override preview failed")
                    handle_ui_exception("Topic preview failed.", exc)

                if st.button("Generate AI summary", key=f"summary_{idx}_{result.file_id}"):
                    if not st.session_state.get("ai_enabled"):
                        st.warning("Enable AI summary in the sidebar first.")
                    else:
                        try:
                            suggestion = generate_summary_suggestion(computed, processor=context.processor)
                            st.session_state.review_summaries[result.file_id] = suggestion.summary
                            st.info(f"Summary: {safe_display_text(suggestion.summary)}")
                            if suggestion.llm_tags:
                                st.caption(f"AI tags: {safe_display_text(', '.join(suggestion.llm_tags))}")
                        except Exception as exc:
                            logger.exception("summary generation failed")
                            handle_ui_exception("AI summary generation failed.", exc)

                saved_summary = st.session_state.review_summaries.get(result.file_id) or result.summary
                if saved_summary:
                    st.write(f"**Summary**: {safe_display_text(saved_summary)}")

    if st.button("Confirm reviewed files", key="confirm_button"):
        try:
            st.session_state.confirmed_results = build_confirmed_results(
                analysis_results,
                processor=context.processor,
                selected_topics=selected_topics,
                summaries=st.session_state.review_summaries,
            )
            st.success("Reviewed files are ready for the Execute tab.")
        except Exception as exc:
            logger.exception("build_confirmed_results failed")
            handle_ui_exception("Review confirmation failed.", exc)
