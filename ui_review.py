from __future__ import annotations

import logging

import streamlit as st

from i18n import get_current_language, t
from services import (
    AnalysisResult,
    apply_manual_topic_override,
    build_confirmed_results,
    generate_summary_suggestion,
)
from topic_taxonomy import canonical_topics_for_file_type, normalize_topic_key, topic_display_label
from ui_common import UIContext, handle_ui_exception, is_debug, safe_display_text
from ui_renderers import render_video_details

logger = logging.getLogger(__name__)


def _tag_options_for(file_type: str) -> list[str]:
    return list(canonical_topics_for_file_type(file_type))


def _ai_summary_disclosure(locale: str) -> str:
    if locale == "zh-TW":
        return "AI 摘要為選用功能，會將最多約 6000 個擷取字元傳送到已設定的外部 OpenAI 服務。"
    return "AI summary is optional and sends up to about 6000 extracted characters to the configured external OpenAI service."


def render_review(context: UIContext) -> None:
    st.header(t("review.title"))
    markdown = getattr(st, "markdown", None)
    if callable(markdown):
        markdown(t("review.description"))
    analysis_results_raw = st.session_state.get("analysis_results")
    if not analysis_results_raw:
        st.info(t("review.empty"))
        return
    if not isinstance(analysis_results_raw, list):
        st.error(t("review.invalid_format"))
        if is_debug():
            st.json({"type": str(type(analysis_results_raw))})
        return

    analysis_results: list[AnalysisResult] = analysis_results_raw
    selected_topics: dict[int, str] = {}
    review_warnings: list[str] = []
    locale = get_current_language()

    for idx, result in enumerate(analysis_results):
        safe_name = safe_display_text(result.original_name)
        normalized_main_topic = normalize_topic_key(result.main_topic)
        with st.expander(f"{idx + 1}. {safe_name}", expanded=(idx == 0)):
            col1, col2 = st.columns([1, 2])
            with col1:
                st.subheader(t("review.preview_title"))
                if result.preview_path and context.storage.path_exists(result.preview_path):
                    try:
                        st.image(str(result.preview_path), use_container_width=True)
                    except Exception as exc:
                        if is_debug():
                            st.exception(exc)
                        else:
                            st.info(t("review.preview_load_failed"))
                elif result.file_type == "video":
                    st.warning(t("review.video_thumbnail_unavailable"))
                else:
                    st.info(t("review.preview_unavailable"))

            with col2:
                st.subheader(t("review.analysis_title"))
                st.write(f"**{t('review.file_name')}**: {safe_name}")
                st.write(f"**{t('review.file_type')}**: {safe_display_text(result.file_type)}")
                st.write(f"**{t('review.date')}**: {safe_display_text(result.standard_date)}")
                if str(getattr(result, "analysis_status", "OK") or "OK") in {"WARNING", "PARTIAL"}:
                    st.warning(t("review.degraded_warning"))
                    if getattr(result, "last_error", None):
                        st.caption(t("review.last_error", message=safe_display_text(result.last_error)))
                    if is_debug() and getattr(result, "step_timings", None):
                        st.caption(t("review.step_timings"))
                        st.json(result.step_timings or {})

                if result.file_type == "video":
                    render_video_details(result.metadata or {})

                if result.is_scanned:
                    st.warning(t("review.scanned_warning"))
                notes = (result.metadata or {}).get("notes")
                if notes:
                    note_lines = notes if isinstance(notes, list) else [str(notes)]
                    st.info(f"{t('review.notes')}\n- " + "\n- ".join(safe_display_text(note) for note in note_lines))

                tag_options = _tag_options_for(result.file_type)
                if normalized_main_topic not in tag_options:
                    review_warnings.append(
                        f"{result.original_name}: unknown topic '{result.main_topic}' is not being auto-converted."
                    )
                select_index = tag_options.index(normalized_main_topic) if normalized_main_topic in tag_options else None
                try:
                    new_topic = st.selectbox(
                        t("review.topic_label"),
                        tag_options,
                        index=select_index if select_index is not None else 0,
                        key=f"topic_{idx}_{result.file_id}",
                        format_func=lambda key: topic_display_label(key, locale=locale),
                    )
                except TypeError:
                    new_topic = st.selectbox(
                        t("review.topic_label"),
                        tag_options,
                        index=select_index if select_index is not None else 0,
                        key=f"topic_{idx}_{result.file_id}",
                    )
                selected_topics[result.file_id] = normalize_topic_key(new_topic)
                if select_index is None:
                    st.warning(
                        t("review.topic_preview_failed")
                        + f" Current stored topic: {safe_display_text(result.main_topic)}"
                    )

                computed = result
                try:
                    computed = apply_manual_topic_override(
                        result,
                        processor=context.processor,
                        chosen_topic=normalize_topic_key(new_topic),
                        summary=st.session_state.review_summaries.get(result.file_id),
                    )
                    st.caption(t("review.classification_reason"))
                    st.code(str(computed.classification_reason or ""))
                    st.caption(t("review.decision_reason"))
                    st.code(str(computed.final_decision_reason or ""))
                except Exception as exc:
                    logger.exception("manual override preview failed")
                    handle_ui_exception(t("review.topic_preview_failed"), exc)

                st.caption(safe_display_text(_ai_summary_disclosure(locale)))
                if st.button(t("review.generate_ai_summary"), key=f"summary_{idx}_{result.file_id}"):
                    if not st.session_state.get("ai_enabled"):
                        st.warning(t("review.enable_ai_first"))
                    else:
                        try:
                            suggestion = generate_summary_suggestion(computed, processor=context.processor)
                            result.summary_status = suggestion.status
                            result.summary_error = suggestion.error
                            if suggestion.summary:
                                result.summary = suggestion.summary
                                st.session_state.review_summaries[result.file_id] = suggestion.summary
                                st.info(t("review.summary_value", summary=safe_display_text(suggestion.summary)))
                            elif suggestion.error:
                                st.warning(safe_display_text(suggestion.error))
                            if suggestion.llm_tags:
                                st.caption(t("review.ai_tags", tags=safe_display_text(", ".join(suggestion.llm_tags))))
                        except Exception as exc:
                            logger.exception("summary generation failed")
                            handle_ui_exception(t("review.generate_ai_summary"), exc)

                saved_summary = st.session_state.review_summaries.get(result.file_id) or result.summary
                if saved_summary:
                    st.write(f"**{t('review.summary_label')}**: {safe_display_text(saved_summary)}")

    for warning in review_warnings:
        st.warning(safe_display_text(warning))

    if st.button(t("review.confirm_button"), key="confirm_button"):
        try:
            st.session_state.confirmed_results = build_confirmed_results(
                analysis_results,
                processor=context.processor,
                selected_topics=selected_topics,
                summaries=st.session_state.review_summaries,
            )
            st.success(t("review.confirm_success"))
        except Exception as exc:
            logger.exception("build_confirmed_results failed")
            handle_ui_exception(t("review.confirm_failed"), exc)
