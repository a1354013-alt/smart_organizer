from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from typing import Any

from contracts import validate_extracted_metadata
from core import FileProcessor
from services_models import AnalysisResult
from storage import StorageManager
from storage_lifecycle import MissingTemporaryFileError
from topic_taxonomy import normalize_topic_key

logger = logging.getLogger(__name__)


def _processing_options(options: Mapping[str, Any] | None) -> dict[str, Any]:
    final = dict(options or {})
    final.setdefault("enable_pdf_preview", False)
    final.setdefault("enable_ocr", False)
    final.setdefault("pdf_text_max_pages", 3)
    final.setdefault("pdf_text_timeout_seconds", 10)
    final.setdefault("pdf_preview_timeout_seconds", 10)
    final.setdefault("ocr_timeout_seconds", 15)
    final.setdefault("video_metadata_timeout_seconds", 10)
    final.setdefault("video_thumbnail_timeout_seconds", 10)
    return final


def _analysis_result_from_record(record: Mapping[str, object]) -> AnalysisResult | None:
    status = str(record.get("status") or "").upper()
    main_topic = normalize_topic_key(record.get("main_topic"))
    if status != "PROCESSED" or not main_topic:
        return None
    return AnalysisResult(
        file_id=int(str(record["file_id"])),
        original_name=str(record.get("original_name") or record.get("safe_name") or "uploaded file"),
        file_type=str(record.get("file_type") or "document"),
        standard_date=str(record.get("standard_date") or ""),
        main_topic=main_topic,
        suggested_main_topic=main_topic,
        tag_scores={main_topic: 1.0},
        classification_reason=str(record.get("classification_reason") or "Restored from stored analysis metadata."),
        final_decision_reason=str(record.get("final_decision_reason") or "Restored after interrupted session."),
        metadata=validate_extracted_metadata(
            {
                "file_type": record.get("file_type") or "document",
                "standard_date": record.get("standard_date") or "",
                "extracted_text": "",
                "is_scanned": bool(record.get("is_scanned")),
                "preview_path": record.get("preview_path"),
                "ocr_error": None,
                "notes": ["Restored from stored analysis metadata."],
            }
        ),
        preview_path=str(record.get("preview_path")) if record.get("preview_path") else None,
        is_scanned=bool(record.get("is_scanned")),
        summary=str(record.get("summary")) if record.get("summary") else None,
        summary_status=str(record.get("summary_status")) if record.get("summary_status") else None,
        summary_error=str(record.get("summary_error")) if record.get("summary_error") else None,
        analysis_status="OK",
        last_error=str(record.get("last_error")) if record.get("last_error") else None,
    )


def reanalyze_unfinished_record(
    *,
    storage: StorageManager,
    processor: FileProcessor,
    file_id: int,
    processing_options: Mapping[str, Any] | None = None,
) -> AnalysisResult:
    record, temp_path = storage.prepare_unfinished_record_for_analysis(int(file_id))
    step_timings: dict[str, float] = {}
    options = _processing_options(processing_options)
    options["_timings"] = step_timings
    started = time.perf_counter()
    try:
        metadata = validate_extracted_metadata(processor.extract_metadata(temp_path, options))
        step_timings["extract_metadata_total"] = round(time.perf_counter() - started, 4)
        main_topic, tag_scores, classification_reason = processor.classify_multi_tag(
            metadata,
            str(record.get("original_name") or temp_path),
            return_reason=True,
        )
        result = AnalysisResult(
            file_id=int(file_id),
            original_name=str(record.get("original_name") or record.get("safe_name") or "uploaded file"),
            file_type=str(metadata.get("file_type") or record.get("file_type") or "document"),
            standard_date=str(metadata.get("standard_date") or ""),
            main_topic=normalize_topic_key(main_topic),
            suggested_main_topic=normalize_topic_key(main_topic),
            tag_scores=dict(tag_scores or {}),
            classification_reason=classification_reason or "",
            final_decision_reason="Re-analyzed from saved temporary upload.",
            metadata=metadata,
            preview_path=metadata.get("preview_path"),
            is_scanned=bool(metadata.get("is_scanned", False)),
            analysis_status="OK",
            step_timings=step_timings,
        )
        storage.update_file_metadata(
            int(file_id),
            {
                "standard_date": result.standard_date,
                "main_topic": result.main_topic,
                "summary": result.summary or "",
                "summary_status": result.summary_status,
                "summary_error": result.summary_error,
                "content": metadata.get("extracted_text") or "",
                "is_scanned": bool(result.is_scanned),
                "preview_path": result.preview_path,
                "classification_reason": result.classification_reason,
                "final_decision_reason": result.final_decision_reason,
                "manual_override": False,
                "decision_source": "RULE_REANALYZE",
                "tag_scores": result.tag_scores,
            },
        )
        return result
    except MissingTemporaryFileError:
        raise
    except Exception as exc:
        message = f"re-analysis failed: {type(exc).__name__}: {exc}"
        storage.mark_unfinished_error(int(file_id), message)
        raise RuntimeError(message) from exc


def resume_unfinished_record(
    *,
    storage: StorageManager,
    processor: FileProcessor,
    file_id: int,
    processing_options: Mapping[str, Any] | None = None,
) -> AnalysisResult:
    record, _temp_path = storage.prepare_unfinished_record_for_analysis(int(file_id))
    restored = _analysis_result_from_record(record)
    if restored is not None:
        return restored
    return reanalyze_unfinished_record(
        storage=storage,
        processor=processor,
        file_id=int(file_id),
        processing_options=processing_options,
    )


def discard_unfinished_record(*, storage: StorageManager, file_id: int) -> dict[str, object]:
    return storage.discard_unfinished_record(int(file_id))
