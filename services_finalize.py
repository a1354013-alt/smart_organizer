from __future__ import annotations

import logging
from typing import Callable, Iterable, Mapping, Any

from contracts import validate_extracted_metadata
from core import FileProcessor
from storage import StorageManager

from services_models import AnalysisResult, ExecutionResult

logger = logging.getLogger(__name__)


def _log_context(**fields: object) -> str:
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "", [])]
    return f" [{', '.join(parts)}]" if parts else ""


def persist_confirmed_metadata(result: AnalysisResult, *, storage: StorageManager) -> None:
    if result.manual_override:
        decision_source = "MANUAL_OVERRIDE"
        last_manual_topic = result.main_topic
        last_manual_reason = result.final_decision_reason
    else:
        decision_source = "RULE"
        last_manual_topic = None
        last_manual_reason = None
    storage.update_file_metadata(
        result.file_id,
        {
            "standard_date": result.standard_date,
            "main_topic": result.main_topic,
            "summary": result.summary or "",
            "content": (result.metadata or {}).get("extracted_text", "") or "",
            "is_scanned": bool(result.is_scanned),
            "preview_path": result.preview_path,
            "classification_reason": result.classification_reason,
            "final_decision_reason": result.final_decision_reason,
            "manual_override": bool(result.manual_override),
            "decision_source": decision_source,
            "last_manual_topic": last_manual_topic,
            "last_manual_reason": last_manual_reason,
            "tag_scores": result.tag_scores or {},
        },
    )
    logger.info(
        "persist_confirmed_metadata%s",
        _log_context(
            file_id=result.file_id,
            original_name=result.original_name,
            decision_source=decision_source,
            main_topic=result.main_topic,
        ),
    )


def finalize_one_file(result: AnalysisResult, *, storage: StorageManager) -> ExecutionResult:
    try:
        persist_confirmed_metadata(result, storage=storage)
        new_path = storage.finalize_organization(
            result.file_id,
            result.standard_date,
            result.main_topic,
            result.original_name,
        )
        logger.info(
            "finalize_one_file success%s",
            _log_context(file_id=result.file_id, original_name=result.original_name, status="SUCCESS", path=new_path),
        )
        return ExecutionResult(original_name=result.original_name, status="SUCCESS", new_path=new_path)
    except Exception:
        logger.error(
            "finalize_one_file failed%s",
            _log_context(file_id=result.file_id, original_name=result.original_name, status="FAILED"),
            exc_info=True,
        )
        return ExecutionResult(original_name=result.original_name, status="FAILED", file_id=result.file_id, new_path=None)


def finalize_batch(
    results: Iterable[AnalysisResult],
    *,
    storage: StorageManager,
    progress_callback: Callable[[int, int, AnalysisResult], None] | None = None,
) -> list[ExecutionResult]:
    result_list = list(results)
    execution_results: list[ExecutionResult] = []
    total = len(result_list)
    logger.info("finalize_batch start%s", _log_context(files=total))
    for index, result in enumerate(result_list, start=1):
        if progress_callback is not None:
            progress_callback(index, total, result)
        execution_results.append(finalize_one_file(result, storage=storage))
    logger.info(
        "finalize_batch done%s",
        _log_context(
            files=total,
            success=sum(1 for item in execution_results if item.status == "SUCCESS"),
            failed=sum(1 for item in execution_results if item.status != "SUCCESS"),
        ),
    )
    return execution_results


def reclassify_record(
    *,
    storage: StorageManager,
    processor: FileProcessor,
    file_id: int,
    processing_options: Mapping[str, Any] | None = None,
) -> str:
    info = storage.get_file_by_id(int(file_id))
    if not info:
        raise ValueError("record not found")

    path = info.get("final_path") or info.get("temp_path")
    if not path or not storage.path_exists(str(path)):
        raise FileNotFoundError("file not found")

    metadata = validate_extracted_metadata(processor.extract_metadata(path, dict(processing_options or {})))
    main_topic, tag_scores, reason = processor.classify_multi_tag(metadata, info.get("original_name") or str(path), return_reason=True)

    storage.update_file_metadata(
        int(file_id),
        {
            "standard_date": metadata.get("standard_date"),
            "main_topic": main_topic,
            "summary": info.get("summary") or "",
            "content": metadata.get("extracted_text") or "",
            "is_scanned": metadata.get("is_scanned") or False,
            "preview_path": metadata.get("preview_path"),
            "classification_reason": reason,
            "final_decision_reason": "重新分類（規則引擎）",
            "manual_override": False,
            "decision_source": "RULE_RECLASSIFY",
            "tag_scores": tag_scores,
        },
    )
    logger.info("reclassify_record%s", _log_context(file_id=file_id, path=path, decision_source="RULE_RECLASSIFY", main_topic=main_topic))
    return main_topic
