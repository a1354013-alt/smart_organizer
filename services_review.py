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
        f"手動覆寫：選擇「{chosen_topic}」（規則建議「{suggested}」）"
        if manual
        else "系統預設決策"
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


def build_confirmed_results(results: list[AnalysisResult]) -> list[AnalysisResult]:
    confirmed: list[AnalysisResult] = []
    for r in results:
        confirmed.append(
            AnalysisResult(
                file_id=r.file_id,
                original_name=r.original_name,
                file_type=r.file_type,
                standard_date=r.standard_date,
                main_topic=r.main_topic,
                suggested_main_topic=r.suggested_main_topic,
                tag_scores=dict(r.tag_scores or {}),
                classification_reason=r.classification_reason,
                final_decision_reason=r.final_decision_reason,
                metadata=r.metadata,
                preview_path=r.preview_path,
                is_scanned=r.is_scanned,
                summary=r.summary,
                manual_override=bool(r.manual_override),
            )
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
