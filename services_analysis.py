from __future__ import annotations

import io
import logging
from typing import Any, Callable, Iterable, Mapping

from contracts import validate_extracted_metadata
from core import FileProcessor
from storage import StorageManager

from services_models import AnalysisResult, BatchAnalysisOutcome, DuplicateInfo, UploadedFileData

logger = logging.getLogger(__name__)


def _log_context(**fields: object) -> str:
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "", [])]
    return f" [{', '.join(parts)}]" if parts else ""


def analyze_one_upload(
    uploaded: UploadedFileData,
    *,
    processor: FileProcessor,
    storage: StorageManager,
    processing_options: Mapping[str, Any] | None = None,
) -> tuple[AnalysisResult | None, DuplicateInfo | None, str | None]:
    try:
        file_hash = processor.get_file_hash(io.BytesIO(uploaded.content))

        file_type_hint = "photo" if (uploaded.mime_type or "").startswith("image") else "document"

        created = storage.create_temp_file(uploaded.name, uploaded.content, file_hash, file_type_hint)

        if not created.get("success"):
            if created.get("reason") == "DUPLICATE":
                dup_status = created.get("status", "UNKNOWN")
                if dup_status == "COMPLETED":
                    return (
                        None,
                        DuplicateInfo(
                            filename=uploaded.name,
                            status="COMPLETED",
                            final_path=str(created.get("final_path") or ""),
                            display=f"{uploaded.name} (已存在)",
                        ),
                        None,
                    )
                return (
                    None,
                    DuplicateInfo(
                        filename=uploaded.name,
                        status="PENDING",
                        display=f"{uploaded.name} (已存在待整理)",
                    ),
                    None,
                )
            return None, None, f"建立暫存檔案失敗：{uploaded.name}"

        file_id = int(created["file_id"])
        temp_path = storage.get_file_path(file_id)
        if not temp_path:
            return None, None, f"找不到暫存檔案路徑：{uploaded.name}"

        metadata = validate_extracted_metadata(processor.extract_metadata(temp_path, dict(processing_options or {})))
        main_topic, tag_scores, classification_reason = processor.classify_multi_tag(
            metadata,
            uploaded.name,
            return_reason=True,
        )

        suggested_main_topic = main_topic
        return (
            AnalysisResult(
                file_id=file_id,
                original_name=uploaded.name,
                file_type=metadata.get("file_type") or "unknown",
                standard_date=metadata.get("standard_date") or "",
                main_topic=main_topic,
                suggested_main_topic=suggested_main_topic,
                tag_scores=dict(tag_scores or {}),
                classification_reason=classification_reason or "",
                final_decision_reason="系統預設決策",
                metadata=metadata,
                preview_path=metadata.get("preview_path"),
                is_scanned=bool(metadata.get("is_scanned", False)),
            ),
            None,
            None,
        )
    except Exception:
        logger.error("analyze_one_upload failed%s", _log_context(original_name=uploaded.name), exc_info=True)
        return None, None, f"分析失敗：{uploaded.name}"


def analyze_upload_batch(
    uploads: Iterable[UploadedFileData],
    *,
    processor: FileProcessor,
    storage: StorageManager,
    processing_options: Mapping[str, Any] | None = None,
    progress_callback: Callable[[int, int, UploadedFileData], None] | None = None,
) -> BatchAnalysisOutcome:
    upload_list = list(uploads)
    total = len(upload_list)
    logger.info("analyze_upload_batch start%s", _log_context(files=total))
    results: list[AnalysisResult] = []
    duplicates: list[DuplicateInfo] = []
    errors: list[str] = []

    for index, uploaded in enumerate(upload_list, start=1):
        if progress_callback is not None:
            progress_callback(index, total, uploaded)
        analyzed, dup, err = analyze_one_upload(
            uploaded,
            processor=processor,
            storage=storage,
            processing_options=processing_options,
        )
        if analyzed is not None:
            results.append(analyzed)
        if dup is not None:
            duplicates.append(dup)
        if err is not None:
            errors.append(err)

    logger.info(
        "analyze_upload_batch done%s",
        _log_context(files=total, analyzed=len(results), duplicates=len(duplicates), errors=len(errors)),
    )
    return BatchAnalysisOutcome(results=results, duplicates=duplicates, errors=errors)


def analyze_upload_batch_async(
    uploads: Iterable[UploadedFileData],
    *,
    processor: FileProcessor,
    storage: StorageManager,
    processing_options: Mapping[str, Any] | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
    max_workers: int = 4,
) -> BatchAnalysisOutcome:
    from async_processor import AsyncProcessor, ProgressState

    upload_list = list(uploads)
    total = len(upload_list)
    logger.info("analyze_upload_batch_async start%s", _log_context(files=total))

    async_proc = AsyncProcessor(max_workers=max_workers)
    results: list[AnalysisResult] = []
    duplicates: list[DuplicateInfo] = []
    errors: list[str] = []

    def process_single(uploaded: UploadedFileData) -> tuple[AnalysisResult | None, DuplicateInfo | None, str | None]:
        try:
            return analyze_one_upload(
                uploaded,
                processor=processor,
                storage=storage,
                processing_options=processing_options,
            )
        except Exception as e:  # pragma: no cover
            return None, None, f"{uploaded.name}: {e}"

    def on_progress(progress: ProgressState):
        if progress_callback:
            progress_callback(progress.current, progress.total)
        for error_info in progress.errors[-1:]:
            logger.warning("Async processing error: %s - %s", error_info["file"], error_info["error"])

    outcomes = async_proc.process_batch(
        items=upload_list,
        process_fn=process_single,
        progress_callback=on_progress,
        item_name="檔案",
    )

    for outcome in outcomes:
        if outcome is None:
            errors.append("Async processing failed: empty outcome")
            continue
        analyzed, dup, err = outcome
        if analyzed is not None:
            results.append(analyzed)
        if dup is not None:
            duplicates.append(dup)
        if err is not None:
            errors.append(err)

    logger.info(
        "analyze_upload_batch_async done%s",
        _log_context(files=total, analyzed=len(results), duplicates=len(duplicates), errors=len(errors)),
    )
    return BatchAnalysisOutcome(results=results, duplicates=duplicates, errors=errors)
