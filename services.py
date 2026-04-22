from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from contracts import ExtractedMetadata, validate_extracted_metadata
from core import FileProcessor, FileUtils
from storage import StorageManager

logger = logging.getLogger(__name__)


def _log_context(**fields: object) -> str:
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "", [])]
    return f" [{', '.join(parts)}]" if parts else ""


@dataclass(frozen=True, slots=True)
class UploadedFileData:
    name: str
    content: bytes
    mime_type: str = ""


@dataclass(frozen=True, slots=True)
class DuplicateInfo:
    filename: str
    status: str
    display: str
    final_path: str | None = None


@dataclass(slots=True)
class AnalysisResult:
    file_id: int
    original_name: str
    file_type: str
    standard_date: str
    main_topic: str
    suggested_main_topic: str
    tag_scores: dict[str, float]
    classification_reason: str
    final_decision_reason: str
    metadata: ExtractedMetadata
    preview_path: str | None
    is_scanned: bool
    summary: str | None = None
    manual_override: bool = False


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    original_name: str
    status: str  # "SUCCESS" | "FAILED"
    new_path: str | None = None
    file_id: int | None = None


@dataclass(frozen=True, slots=True)
class SummarySuggestion:
    summary: str
    llm_tags: list[str]


@dataclass(frozen=True, slots=True)
class BatchAnalysisOutcome:
    results: list[AnalysisResult]
    duplicates: list[DuplicateInfo]
    errors: list[str]


def analyze_one_upload(
    uploaded: UploadedFileData,
    *,
    processor: FileProcessor,
    storage: StorageManager,
    processing_options: Mapping[str, Any] | None = None,
) -> tuple[AnalysisResult | None, DuplicateInfo | None, str | None]:
    """
    Analyze a single upload into an AnalysisResult.

    Returns:
      (analysis_result, duplicate_info, user_facing_error_message)
    """
    try:
        file_hash = processor.get_file_hash(io.BytesIO(uploaded.content))

        # file_type is only a hint; Storage must infer/validate final type.
        file_type_hint = "photo" if (uploaded.mime_type or "").startswith("image") else "document"

        created = storage.create_temp_file(
            uploaded.name,
            uploaded.content,
            file_hash,
            file_type_hint,
        )

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
                            display=f"{uploaded.name} (已整理)",
                        ),
                        None,
                    )
                return (
                    None,
                    DuplicateInfo(
                        filename=uploaded.name,
                        status="PENDING",
                        display=f"{uploaded.name} (已在待整理清單)",
                    ),
                    None,
                )
            return None, None, f"建立暫存檔失敗：{uploaded.name}"

        file_id = int(created["file_id"])
        temp_path = storage.get_file_path(file_id)
        if not temp_path:
            return None, None, f"找不到暫存檔路徑：{uploaded.name}"

        metadata = validate_extracted_metadata(
            processor.extract_metadata(temp_path, dict(processing_options or {}))
        )
        main_topic, tag_scores, classification_reason = processor.classify_multi_tag(
            metadata, uploaded.name, return_reason=True
        )

        metadata["standard_date"] = FileUtils.normalize_standard_date(metadata.get("standard_date"))
        file_type = str(metadata.get("file_type") or "")
        standard_date = str(metadata.get("standard_date") or FileUtils.DEFAULT_UNKNOWN_DATE)

        return (
            AnalysisResult(
                file_id=file_id,
                original_name=uploaded.name,
                file_type=file_type,
                standard_date=standard_date,
                main_topic=main_topic,
                suggested_main_topic=main_topic,
                tag_scores=dict(tag_scores or {}),
                classification_reason=classification_reason or "",
                final_decision_reason="採用規則建議",
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
    """
    批量分析上傳檔案 (同步版本，保持向後相容)
    """
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
    """
    批量分析上傳檔案（並行處理版本，支援進度回調）
    
    Args:
        uploads: 上傳檔案列表
        processor: 檔案處理器
        storage: 儲存管理器
        processing_options: 處理選項
        progress_callback: 進度回調 (current, total)
        max_workers: 最大執行緒數
    
    Returns:
        BatchAnalysisOutcome
    """
    from async_processor import AsyncProcessor, ProgressState
    
    upload_list = list(uploads)
    total = len(upload_list)
    logger.info("analyze_upload_batch_async start%s", _log_context(files=total))
    
    async_proc = AsyncProcessor(max_workers=max_workers)
    results: list[AnalysisResult] = []
    duplicates: list[DuplicateInfo] = []
    errors: list[str] = []
    
    def process_single(uploaded: UploadedFileData) -> tuple[AnalysisResult | None, DuplicateInfo | None, str | None]:
        """單個檔案處理函式"""
        try:
            return analyze_one_upload(
                uploaded,
                processor=processor,
                storage=storage,
                processing_options=processing_options,
            )
        except Exception as e:  # pragma: no cover - defensive: AsyncProcessor already handles exceptions.
            return None, None, f"{uploaded.name}: {e}"
    
    def on_progress(progress: ProgressState):
        """進度回調"""
        if progress_callback:
            progress_callback(progress.current, progress.total)
        for error_info in progress.errors[-1:]:  # 記錄最新錯誤
            logger.warning("Async processing error: %s - %s", error_info["file"], error_info["error"])
    
    # 執行非同步處理
    outcomes = async_proc.process_batch(
        items=upload_list,
        process_fn=process_single,
        progress_callback=on_progress,
        item_name="檔案",
    )
    
    # 整理結果
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


def persist_confirmed_metadata(
    result: AnalysisResult,
    *,
    storage: StorageManager,
) -> None:
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


def apply_manual_topic_override(
    result: AnalysisResult,
    *,
    processor: FileProcessor,
    chosen_topic: str,
    summary: str | None = None,
) -> AnalysisResult:
    """
    Apply manual topic override in a single place (UI should not mutate decision fields directly).

    - Updates main_topic
    - Syncs tag_scores
    - Generates final_decision_reason / manual_override flags
    """
    suggested = result.suggested_main_topic or result.main_topic
    chosen_topic = chosen_topic or result.main_topic
    manual = bool(chosen_topic and chosen_topic != suggested)
    reason = (
        f"手動覆寫：選擇「{chosen_topic}」（規則建議「{suggested}」）"
        if manual
        else "採用規則建議"
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


def build_confirmed_results(
    analysis_results: Iterable[AnalysisResult],
    *,
    processor: FileProcessor,
    selected_topics: Mapping[int, str],
    summaries: Mapping[int, str],
) -> list[AnalysisResult]:
    confirmed: list[AnalysisResult] = []
    for result in analysis_results:
        confirmed.append(
            apply_manual_topic_override(
                result,
                processor=processor,
                chosen_topic=selected_topics.get(result.file_id, result.main_topic),
                summary=summaries.get(result.file_id) or result.summary,
            )
        )
    return confirmed


def generate_summary_suggestion(
    result: AnalysisResult,
    *,
    processor: FileProcessor,
) -> SummarySuggestion:
    extracted_text = (result.metadata or {}).get("extracted_text", "")
    summary, llm_tags = processor.get_llm_summary(
        extracted_text,
        result.file_type,
        enabled=True,
    )
    suggestion = SummarySuggestion(summary=summary, llm_tags=list(llm_tags or []))
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


def finalize_one_file(
    result: AnalysisResult,
    *,
    storage: StorageManager,
) -> ExecutionResult:
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
            _log_context(
                file_id=result.file_id,
                original_name=result.original_name,
                status="SUCCESS",
                path=new_path,
            ),
        )
        return ExecutionResult(original_name=result.original_name, status="SUCCESS", new_path=new_path)
    except Exception:
        logger.error(
            "finalize_one_file failed%s",
            _log_context(file_id=result.file_id, original_name=result.original_name, status="FAILED"),
            exc_info=True,
        )
        return ExecutionResult(
            original_name=result.original_name, status="FAILED", file_id=result.file_id, new_path=None
        )


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
    """
    Re-run rule-based classification for an existing record (no AI).
    Returns the new main_topic.
    """
    info = storage.get_file_by_id(int(file_id))
    if not info:
        raise ValueError("record not found")

    path = info.get("final_path") or info.get("temp_path")
    if not path or not storage.path_exists(path):
        raise FileNotFoundError("file not found")

    metadata = validate_extracted_metadata(processor.extract_metadata(path, dict(processing_options or {})))
    main_topic, tag_scores, reason = processor.classify_multi_tag(
        metadata,
        info.get("original_name") or str(path),
        return_reason=True,
    )

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
    logger.info(
        "reclassify_record%s",
        _log_context(file_id=file_id, path=path, decision_source="RULE_RECLASSIFY", main_topic=main_topic),
    )
    return main_topic
