from __future__ import annotations

import logging

from core import FileProcessor

from services_models import AnalysisResult, SummarySuggestion

logger = logging.getLogger(__name__)


def _log_context(**fields: object) -> str:
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "", [])]
    return f" [{', '.join(parts)}]" if parts else ""


def apply_manual_topic_override(
    result: AnalysisResult,
    *,
    processor: FileProcessor,
    chosen_topic: str,
    summary: str | None = None,
) -> AnalysisResult:
    suggested = result.suggested_main_topic or result.main_topic
    chosen_topic = chosen_topic or result.main_topic
    manual = bool(chosen_topic and chosen_topic != suggested)
    reason = (
        f"Manual override from '{suggested}' to '{chosen_topic}'."
        if manual
        else "User confirmed the suggested topic without changes."
    )

    synced = processor.sync_manual_topic(chosen_topic, result.tag_scores, result.file_type)

    updated = AnalysisResult(
        file_id=result.file_id,
        original_name=result.original_name,
        file_type=result.file_type,
        standard_date=result.standard_date,
        main_topic=chosen_topic,
        suggested_main_topic=result.suggested_main_topic,
        tag_scores=dict(synced or {}),
        classification_reason=result.classification_reason,
        final_decision_reason=reason,
        metadata=result.metadata,
        preview_path=result.preview_path,
        is_scanned=result.is_scanned,
        summary=summary if summary is not None else result.summary,
        manual_override=manual,
        analysis_status=result.analysis_status,
        last_error=result.last_error,
        step_timings=dict(result.step_timings or {}) or None,
    )
    logger.info(
        "apply_manual_topic_override%s",
        _log_context(
            file_id=result.file_id,
            original_name=result.original_name,
            suggested=result.suggested_main_topic,
            chosen_topic=chosen_topic,
            manual_override=manual,
        ),
    )
    return updated


def _clone_analysis_result(result: AnalysisResult) -> AnalysisResult:
    return AnalysisResult(
        file_id=result.file_id,
        original_name=result.original_name,
        file_type=result.file_type,
        standard_date=result.standard_date,
        main_topic=result.main_topic,
        suggested_main_topic=result.suggested_main_topic,
        tag_scores=dict(result.tag_scores or {}),
        classification_reason=result.classification_reason,
        final_decision_reason=result.final_decision_reason,
        metadata=result.metadata,
        preview_path=result.preview_path,
        is_scanned=result.is_scanned,
        summary=result.summary,
        manual_override=bool(result.manual_override),
        analysis_status=result.analysis_status,
        last_error=result.last_error,
        step_timings=dict(result.step_timings or {}) or None,
    )


def build_confirmed_results(
    results: list[AnalysisResult],
    *,
    processor: FileProcessor | None = None,
    selected_topics: dict[int, str] | None = None,
    summaries: dict[int, str] | None = None,
) -> list[AnalysisResult]:
    confirmed: list[AnalysisResult] = []
    selected_topics = dict(selected_topics or {})
    summaries = dict(summaries or {})

    if selected_topics and processor is None:
        raise ValueError("processor is required when selected_topics are provided")

    for result in results:
        chosen_topic = selected_topics.get(result.file_id, result.main_topic)
        summary = summaries.get(result.file_id, result.summary)

        if processor is not None and (chosen_topic != result.main_topic or summary != result.summary):
            confirmed_result = apply_manual_topic_override(
                result,
                processor=processor,
                chosen_topic=chosen_topic,
                summary=summary,
            )
        else:
            confirmed_result = _clone_analysis_result(result)
            confirmed_result.summary = summary

        confirmed.append(confirmed_result)

    logger.info(
        "build_confirmed_results%s",
        _log_context(
            files=len(confirmed),
            selected_topics=len(selected_topics),
            summaries=len(summaries),
        ),
    )
    return confirmed


def generate_summary_suggestion(
    result: AnalysisResult,
    *,
    processor: FileProcessor,
    enabled: bool = True,
) -> SummarySuggestion:
    text = (result.metadata or {}).get("extracted_text", "") or ""
    summary, tags = processor.get_llm_summary(text, result.file_type, enabled=enabled)
    suggestion = SummarySuggestion(summary=str(summary or ""), llm_tags=list(tags or []))
    logger.info(
        "generate_summary_suggestion%s",
        _log_context(
            file_id=result.file_id,
            original_name=result.original_name,
            file_type=result.file_type,
            summary_chars=len(suggestion.summary),
            llm_tags=len(suggestion.llm_tags),
        ),
    )
    return suggestion
