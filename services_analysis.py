from __future__ import annotations

import io
import logging
import os
import time
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, cast

from contracts import validate_extracted_metadata
from core import FileProcessor
from malware_scanner import MalwareScanner, MalwareScanResult, ScanHealth, ScanPolicy, Verdict
from services_models import AnalysisResult, BatchAnalysisOutcome, DuplicateInfo, UploadedFileData
from storage import MAX_UPLOAD_BATCH_BYTES, MAX_UPLOAD_BYTES, StorageManager
from storage_base import utc_now_iso
from supported_formats import SUPPORTED_VIDEO_SUFFIXES
from topic_taxonomy import normalize_topic_key
from upload_validation import validate_upload_batch

logger = logging.getLogger(__name__)


def _create_temp_file_error(uploaded_name: str, created: Mapping[str, Any]) -> str:
    message = str(created.get("message") or "").strip()
    reason = str(created.get("reason") or "ERROR").strip()
    if message:
        return f"{uploaded_name}: {message}"
    if reason and reason != "ERROR":
        return f"{uploaded_name}: upload failed ({reason})"
    return f"{uploaded_name}: failed to create temporary file"


def _log_context(**fields: object) -> str:
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "", [])]
    return f" [{', '.join(parts)}]" if parts else ""


def _infer_file_type_hint(uploaded: UploadedFileData) -> str:
    mime_type = (uploaded.mime_type or "").lower()
    suffix = os.path.splitext(uploaded.name or "")[1].lower()
    if mime_type.startswith("image"):
        return "photo"
    if mime_type.startswith("video") or suffix in SUPPORTED_VIDEO_SUFFIXES:
        return "video"
    return "document"


def _build_scan_policy(options: Mapping[str, Any]) -> ScanPolicy:
    policy_name = str(options.get("malware_scan_policy") or "standard").strip().lower() or "standard"
    strict = policy_name == "strict"
    return ScanPolicy(
        name=policy_name,
        policy_version=str(options.get("malware_scan_policy_version") or ("strict-v1" if strict else "standard-v1")),
        max_scan_size_bytes=options.get("malware_max_scan_size_bytes"),
        max_file_size_bytes=options.get("malware_max_file_size_bytes"),
        max_archive_recursion=options.get("malware_max_archive_recursion"),
        max_archive_files=options.get("malware_max_archive_files"),
        max_scan_time_seconds=max(1, int(options.get("malware_scan_timeout_seconds", 30))),
        enable_pua=bool(strict or options.get("malware_detect_pua")),
        enable_heuristics=bool(strict or options.get("malware_enable_heuristics")),
        alert_encrypted=bool(strict or options.get("malware_alert_encrypted")),
        alert_broken_executables=bool(strict or options.get("malware_alert_broken_executables")),
        custom_rules_dir=str(options.get("malware_custom_rules_dir") or "").strip() or None,
    )


def _scan_upload_before_processing(
    *,
    uploaded: UploadedFileData,
    file_id: int,
    temp_path: str,
    file_hash: str,
    storage: StorageManager,
    processing_options: Mapping[str, Any],
) -> MalwareScanResult | None:
    if not bool(processing_options.get("enable_malware_scan", False)):
        return None

    policy = _build_scan_policy(processing_options)
    timeout_seconds = max(1, int(processing_options.get("malware_scan_timeout_seconds", 30)))
    scanner = MalwareScanner(
        timeout_seconds=timeout_seconds,
        max_database_age_days=max(1, int(processing_options.get("malware_database_max_age_days", 7))),
        policy=policy,
    )
    record = storage.get_file_by_id(file_id) or {}
    raw_mtime_ns = record.get("mtime_ns")
    mtime_ns = raw_mtime_ns if isinstance(raw_mtime_ns, int) else None
    raw_size_bytes = record.get("size_bytes")
    size_bytes = raw_size_bytes if isinstance(raw_size_bytes, int) else None
    cached = storage.get_malware_scan_cache(
        sha256=file_hash,
        scanner_backend=scanner.get_status().selected_backend,
        database_version=scanner.get_status().database_version,
        database_date=scanner.get_status().database_date,
        scan_policy_version=policy.policy_version,
        size_bytes=size_bytes,
        mtime_ns=mtime_ns,
    )
    if cached is not None:
        result = MalwareScanResult(
            verdict=cast(Verdict, cached.get("verdict") or "not_scanned"),
            scan_health=cast(ScanHealth, cached.get("scan_health") or "incomplete"),
            scanner="ClamAV",
            file_path=temp_path,
            backend=str(cached.get("scanner_backend") or "cache"),
            threat_name=str(cached.get("threat_name") or "").strip() or None,
            message=str(cached.get("message") or "").strip(),
            elapsed_seconds=float(cast(float | int | str, cached.get("elapsed_seconds") or 0.0)),
            engine_version=str(cached.get("engine_version") or "").strip() or None,
            database_version=str(cached.get("database_version") or "").strip() or None,
            database_date=str(cached.get("database_date") or "").strip() or None,
            cache_hit=True,
            file_sha256=file_hash,
        )
        storage.update_file_malware_scan(file_id, result, cache_hit=True)
        return result

    status = scanner.get_status()
    if status.selected_backend == "clamd":
        result = scanner.scan_bytes(uploaded.content, uploaded.name)
    else:
        result = scanner.scan_path(Path(temp_path))
    result = MalwareScanResult(
        verdict=result.verdict,
        scan_health=result.scan_health,
        scanner=result.scanner,
        file_path=temp_path,
        backend=result.backend,
        threat_name=result.threat_name,
        message=result.message,
        elapsed_seconds=result.elapsed_seconds,
        return_code=result.return_code,
        engine_version=result.engine_version,
        database_version=result.database_version,
        database_date=result.database_date,
        cache_hit=False,
        file_sha256=file_hash,
    )
    storage.update_file_malware_scan(file_id, result, cache_hit=False)
    storage.upsert_malware_scan_cache(
        sha256=file_hash,
        canonical_path=temp_path,
        size_bytes=result.file_size,
        mtime_ns=result.file_mtime_ns,
        file_identity=result.file_inode,
        result=result,
        scan_policy_version=policy.policy_version,
    )
    if not result.is_actionably_clean():
        holding_path = storage.move_upload_to_malware_holding(file_id)
        storage.update_file_malware_scan(file_id, result, cache_hit=False, temp_path=holding_path, status_override="BLOCKED")
    return result


def analyze_one_upload(
    uploaded: UploadedFileData,
    *,
    processor: FileProcessor,
    storage: StorageManager,
    processing_options: Mapping[str, Any] | None = None,
) -> tuple[AnalysisResult | None, DuplicateInfo | None, str | None]:
    """Analyze one uploaded file without breaking the whole batch."""
    step_timings: dict[str, float] = {}
    analysis_status = "OK"
    last_error: str | None = None

    try:
        file_hash = processor.get_file_hash(io.BytesIO(uploaded.content))
        file_type_hint = _infer_file_type_hint(uploaded)

        created = storage.create_temp_file(uploaded.name, uploaded.content, file_hash, file_type_hint)
        if not created.get("success"):
            if created.get("reason") == "DUPLICATE":
                dup_status = str(created.get("status", "UNKNOWN"))
                if dup_status == "COMPLETED":
                    return (
                        None,
                        DuplicateInfo(
                            filename=uploaded.name,
                            status="COMPLETED",
                            final_path=str(created.get("final_path") or ""),
                            display=f"{uploaded.name} (already organized)",
                        ),
                        None,
                    )
                return (
                    None,
                    DuplicateInfo(
                        filename=uploaded.name,
                        status=dup_status,
                        display=f"{uploaded.name} (already {dup_status.lower()}; use Records to resume, re-analyze, or discard)",
                    ),
                    None,
                )
            return None, None, _create_temp_file_error(uploaded.name, created)

        file_id = int(created["file_id"])
        temp_path = storage.get_file_path(file_id)
        if not temp_path:
            return None, None, f"Temporary path missing for {uploaded.name}"

        options = dict(processing_options or {})
        malware_result = _scan_upload_before_processing(
            uploaded=uploaded,
            file_id=file_id,
            temp_path=temp_path,
            file_hash=file_hash,
            storage=storage,
            processing_options=options,
        )
        if malware_result is not None and not malware_result.is_actionably_clean():
            return None, None, (
                f"{uploaded.name}: blocked by malware scan "
                f"({malware_result.status}: {malware_result.message or malware_result.threat_name or 'scan blocked'})"
            )

        options.setdefault("enable_pdf_preview", False)
        options.setdefault("enable_ocr", False)
        options.setdefault("pdf_text_max_pages", 3)
        options.setdefault("pdf_text_timeout_seconds", 10)
        options.setdefault("pdf_preview_timeout_seconds", 10)
        options.setdefault("ocr_timeout_seconds", 15)
        options.setdefault("video_metadata_timeout_seconds", 10)
        options.setdefault("video_thumbnail_timeout_seconds", 10)
        options["_timings"] = step_timings

        started = time.perf_counter()
        try:
            metadata = validate_extracted_metadata(processor.extract_metadata(temp_path, options))
        except Exception as exc:
            analysis_status = "PARTIAL"
            last_error = f"extract_metadata failed: {type(exc).__name__}: {exc}"
            metadata = validate_extracted_metadata(
                {
                    "file_type": file_type_hint,
                    "standard_date": "",
                    "extracted_text": "",
                    "is_scanned": False,
                    "preview_path": None,
                    "ocr_error": None,
                    "notes": [last_error],
                }
            )
        finally:
            step_timings["extract_metadata_total"] = round(time.perf_counter() - started, 4)

        try:
            main_topic, tag_scores, classification_reason = processor.classify_multi_tag(
                metadata,
                uploaded.name,
                return_reason=True,
            )
        except Exception as exc:
            analysis_status = "PARTIAL"
            err = f"classify failed: {type(exc).__name__}: {exc}"
            last_error = err if not last_error else f"{last_error} | {err}"
            if metadata.get("file_type") == "photo":
                main_topic = "photo.other"
            elif metadata.get("file_type") == "video":
                main_topic = "video.unclassified"
            else:
                main_topic = "document.other"
            tag_scores = {}
            classification_reason = err

        notes = metadata.get("notes")
        if (
            analysis_status == "OK"
            and isinstance(notes, list)
            and any(
            isinstance(n, str) and any(flag in n.lower() for flag in ("timeout", "fallback", "degraded", "partial"))
            for n in notes
            )
        ):
            analysis_status = "WARNING"

        return (
            AnalysisResult(
                file_id=file_id,
                original_name=uploaded.name,
                file_type=metadata.get("file_type") or "unknown",
                standard_date=metadata.get("standard_date") or "",
                main_topic=normalize_topic_key(main_topic),
                suggested_main_topic=normalize_topic_key(main_topic),
                tag_scores=dict(tag_scores or {}),
                classification_reason=classification_reason or "",
                final_decision_reason="Auto-classified from metadata and filename signals.",
                metadata=metadata,
                preview_path=metadata.get("preview_path"),
                is_scanned=bool(metadata.get("is_scanned", False)),
                malware_verdict=malware_result.verdict if malware_result is not None else "not_scanned",
                malware_scan_health=malware_result.scan_health if malware_result is not None else "incomplete",
                malware_status=malware_result.status if malware_result is not None else "not_scanned",
                malware_scanner_backend=malware_result.backend if malware_result is not None else None,
                malware_scanner_engine_version=malware_result.engine_version if malware_result is not None else None,
                malware_database_version=malware_result.database_version if malware_result is not None else None,
                malware_database_date=malware_result.database_date if malware_result is not None else None,
                malware_threat_name=malware_result.threat_name if malware_result is not None else None,
                malware_message=malware_result.message if malware_result is not None else None,
                malware_scanned_at=utc_now_iso() if malware_result is not None else None,
                malware_elapsed_seconds=malware_result.elapsed_seconds if malware_result is not None else 0.0,
                malware_cache_hit=malware_result.cache_hit if malware_result is not None else False,
                summary_status=None,
                summary_error=None,
                analysis_status=analysis_status,
                last_error=last_error,
                step_timings=step_timings,
            ),
            None,
            None,
        )
    except Exception:
        logger.error("analyze_one_upload failed%s", _log_context(original_name=uploaded.name), exc_info=True)
        return None, None, f"Analysis failed for {uploaded.name}"


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
    validation = validate_upload_batch(
        [(upload.name, len(upload.content)) for upload in upload_list],
        max_file_bytes=MAX_UPLOAD_BYTES,
        max_batch_bytes=MAX_UPLOAD_BATCH_BYTES,
    )

    batch_level_errors = [error.detail for error in validation.errors if error.code == "batch_too_large"]
    if batch_level_errors:
        errors.extend(batch_level_errors)
        return BatchAnalysisOutcome(results=results, duplicates=duplicates, errors=errors)

    for index, uploaded in enumerate(upload_list, start=1):
        upload_errors = [
            error.detail
            for error in validate_upload_batch(
                [(uploaded.name, len(uploaded.content))],
                max_file_bytes=MAX_UPLOAD_BYTES,
                max_batch_bytes=MAX_UPLOAD_BATCH_BYTES,
            ).errors
            if error.code != "batch_too_large"
        ]
        if upload_errors:
            errors.extend(upload_errors)
            continue
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
    validation = validate_upload_batch(
        [(upload.name, len(upload.content)) for upload in upload_list],
        max_file_bytes=MAX_UPLOAD_BYTES,
        max_batch_bytes=MAX_UPLOAD_BATCH_BYTES,
    )
    batch_level_errors = [error.detail for error in validation.errors if error.code == "batch_too_large"]
    if batch_level_errors:
        return BatchAnalysisOutcome(results=results, duplicates=duplicates, errors=batch_level_errors)

    def process_single(uploaded: UploadedFileData) -> tuple[AnalysisResult | None, DuplicateInfo | None, str | None]:
        try:
            upload_errors = [
                error.detail
                for error in validate_upload_batch(
                    [(uploaded.name, len(uploaded.content))],
                    max_file_bytes=MAX_UPLOAD_BYTES,
                    max_batch_bytes=MAX_UPLOAD_BATCH_BYTES,
                ).errors
                if error.code != "batch_too_large"
            ]
            if upload_errors:
                return None, None, " | ".join(upload_errors)
            return analyze_one_upload(
                uploaded,
                processor=processor,
                storage=storage,
                processing_options=processing_options,
            )
        except Exception as exc:  # pragma: no cover
            return None, None, f"{uploaded.name}: {exc}"

    def on_progress(progress: ProgressState) -> None:
        if progress_callback:
            progress_callback(progress.current, progress.total)
        for error_info in progress.errors[-1:]:
            logger.warning("Async processing error: %s - %s", error_info["file"], error_info["error"])

    batch_result = async_proc.process_batch(
        items=upload_list,
        process_fn=process_single,
        progress_callback=on_progress,
        item_name="upload",
    )

    for outcome in batch_result.results:
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
    if batch_result.cancelled:
        errors.append(
            "Async processing cancelled "
            f"(completed={batch_result.completed_count}, skipped={batch_result.skipped_count}, failed={batch_result.failed_count})."
        )

    logger.info(
        "analyze_upload_batch_async done%s",
        _log_context(
            files=total,
            analyzed=len(results),
            duplicates=len(duplicates),
            errors=len(errors),
            cancelled=batch_result.cancelled,
            skipped=batch_result.skipped_count,
        ),
    )
    return BatchAnalysisOutcome(results=results, duplicates=duplicates, errors=errors)
