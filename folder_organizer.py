from __future__ import annotations

import datetime
import hashlib
import os
import re
import shutil
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from difflib import SequenceMatcher
from pathlib import Path

from folder_models import (
    ACTIVE_QUARANTINE_STATUSES,
    QUARANTINE_DIRNAME,
    FolderActionResult,
    FolderOperationResult,
    FolderOperationRow,
    FolderOperationSummary,
    FolderScanRecord,
    FolderScanResult,
    FolderScanStats,
    ManifestCompatibilityError,
    QuarantineStatus,
    Recommendation,
    RiskLevel,
    ScanPathError,
    dict_object,
    human_bytes,
    infer_local_file_kind,
    is_relative_to_path,
    iso_now,
    load_manifest,
    object_list,
    quarantine_dir,
    quarantine_manifest_guard,
    safe_destination,
    safe_int,
    save_manifest,
    string_list,
)

LOW_RISK_SUFFIXES = {".txt", ".log", ".tmp", ".cache", ".bak", ".old", ".fake"}
MANUAL_REVIEW_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
DO_NOT_TOUCH_NAMES = {"readme", "license", "copying", "important", "keep"}
SAME_CONTENT_DUPLICATE = "same_content_duplicate"
SAME_NAME_CANDIDATE = "same_name_candidate"
SIMILAR_NAME_CANDIDATE = "similar_name_candidate"


def _resolve_path(path_value: Path | str) -> Path:
    return Path(path_value).expanduser().resolve()


def validate_scan_root_path(folder_path: str) -> Path:
    normalized = str(folder_path or "").strip().strip('"')
    if not normalized:
        raise ScanPathError("Enter a folder path first.")

    root = Path(normalized).expanduser()
    try:
        stat_result = root.stat()
    except FileNotFoundError as exc:
        raise ScanPathError(f"Scan root does not exist: {root}") from exc
    except PermissionError as exc:
        raise ScanPathError(f"Permission denied for scan root: {root}") from exc
    except OSError as exc:
        detail = exc.strerror or type(exc).__name__
        raise ScanPathError(f"Cannot access scan root {root}: {detail}") from exc

    if not Path(root).is_dir():
        raise ScanPathError(f"Scan root is not a directory: {root}")
    if not os.access(root, os.R_OK | os.X_OK):
        raise ScanPathError(f"Permission denied for scan root: {root}")
    del stat_result
    return root.resolve()


def _scan_root_path(scan_result: dict[str, object]) -> Path:
    return _resolve_path(str(scan_result.get("path") or ""))


def _validate_path_within_root(path_value: Path | str, root: Path, *, label: str) -> Path:
    resolved = _resolve_path(path_value)
    if not is_relative_to_path(resolved, root):
        raise ValueError(f"{label} escapes scan root: {resolved}")
    return resolved


def _validate_quarantine_path(path_value: Path | str, quarantine_root: Path, *, label: str) -> Path:
    resolved = _resolve_path(path_value)
    if not is_relative_to_path(resolved, quarantine_root):
        raise ValueError(f"{label} escapes quarantine root: {resolved}")
    return resolved


def build_quarantine_target_path(
    root: Path,
    original_path: Path | str,
    quarantine_root: Path,
    operation_id: str,
) -> Path:
    resolved_original = _validate_path_within_root(original_path, root, label="selected file")
    relative_path = resolved_original.relative_to(root)
    target = (quarantine_root / operation_id / relative_path).resolve()
    if not is_relative_to_path(target, quarantine_root):
        raise ValueError(f"quarantine target escapes quarantine root: {target}")
    return target


def _is_active_manifest_item(item: dict[str, object]) -> bool:
    return str(item.get("status") or "").upper() in ACTIVE_QUARANTINE_STATUSES


def load_quarantine_items_with_warnings(folder_path: str) -> tuple[list[dict[str, object]], list[str]]:
    root = Path(folder_path).expanduser()
    try:
        items = list_quarantine_items(str(root))
    except ManifestCompatibilityError as exc:
        return [], [f"Quarantine manifest warning: {exc}"]
    return items, []


def _find_active_original(manifest_items: list[dict[str, object]], original_path: Path) -> dict[str, object] | None:
    resolved = str(original_path.resolve())
    for item in manifest_items:
        if _is_active_manifest_item(item) and str(item.get("original_path") or "") == resolved:
            return item
    return None


def recover_quarantine_manifest(folder_path: str) -> dict[str, object]:
    root = Path(folder_path).expanduser().resolve()
    with quarantine_manifest_guard(root):
        manifest = load_manifest(root)
        items = [dict_object(item) for item in object_list(manifest.get("items"))]
        changed = False

        for item in items:
            if str(item.get("status") or "").upper() != QuarantineStatus.MOVING.value:
                continue
            quarantine_path = Path(str(item.get("quarantine_path") or ""))
            original_path = Path(str(item.get("original_path") or ""))
            quarantine_exists = quarantine_path.exists()
            original_exists = original_path.exists()
            if quarantine_exists and not original_exists:
                item["status"] = QuarantineStatus.QUARANTINED.value
                item["last_error"] = ""
                changed = True
            elif original_exists and not quarantine_exists:
                item["status"] = QuarantineStatus.FAILED.value
                item["last_error"] = "Recovered interrupted move before source left original location."
                changed = True
            elif quarantine_exists and original_exists:
                item["status"] = QuarantineStatus.FAILED.value
                item["last_error"] = "Recovery found both original and quarantine copies; manual review required."
                changed = True
            else:
                item["status"] = QuarantineStatus.FAILED.value
                item["last_error"] = "Recovery found neither original nor quarantine file."
                changed = True

        if changed:
            manifest["items"] = items
            save_manifest(root, manifest)
        return {"items": items}


class FolderOrganizer:
    def __init__(self, scan_root: Path | str, quarantine_root: Path | str):
        self.scan_root = Path(scan_root).expanduser().resolve()
        self.quarantine_root = Path(quarantine_root).expanduser().resolve()

    def quarantine_file(self, source_path: Path | str, quarantine_relative_path: Path | str) -> FolderActionResult:
        source = Path(source_path).expanduser().resolve()
        relative_target = Path(quarantine_relative_path)
        target = (self.quarantine_root / relative_target).resolve()

        if not is_relative_to_path(source, self.scan_root):
            return FolderActionResult(
                success=False,
                source=str(source),
                error="source path escapes scan root",
            )
        if relative_target.is_absolute() or not is_relative_to_path(target, self.quarantine_root):
            return FolderActionResult(
                success=False,
                source=str(source),
                target=str(target),
                error="quarantine target escapes quarantine root",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target = safe_destination(target)
        shutil.move(str(source), str(target))
        return FolderActionResult(success=True, source=str(source), target=str(target))

    def restore_file(self, quarantine_path: Path | str, restore_relative_path: Path | str) -> FolderActionResult:
        source = Path(quarantine_path).expanduser().resolve()
        relative_target = Path(restore_relative_path)
        target = (self.scan_root / relative_target).resolve()

        if not is_relative_to_path(source, self.quarantine_root):
            return FolderActionResult(
                success=False,
                source=str(source),
                error="restore source escapes quarantine root",
            )
        if relative_target.is_absolute() or not is_relative_to_path(target, self.scan_root):
            return FolderActionResult(
                success=False,
                source=str(source),
                target=str(target),
                error="restore target escapes scan root",
            )

        target.parent.mkdir(parents=True, exist_ok=True)
        target = safe_destination(target)
        shutil.move(str(source), str(target))
        return FolderActionResult(success=True, source=str(source), target=str(target))


def _candidate_reasons(
    size_bytes: int,
    stale_days_since_touch: int | None,
    large_file_bytes: int,
    *,
    suffix: str,
) -> list[str]:
    reasons: list[str] = []
    if stale_days_since_touch is not None and stale_days_since_touch >= 0:
        reasons.append(f"long unused: last touched {stale_days_since_touch} days ago")
    if size_bytes >= large_file_bytes:
        reasons.append(f"large file: {human_bytes(size_bytes)}")
    if suffix in {".tmp", ".cache", ".log", ".bak", ".old"}:
        reasons.append("temp/cache/log file")
    return reasons


def _reason_codes(reasons: list[str]) -> list[str]:
    codes: list[str] = []
    for reason in reasons:
        lowered = reason.lower()
        if "long unused" in lowered:
            codes.append("long_unused")
        elif "large file" in lowered:
            codes.append("large_file")
        elif "duplicate" in lowered:
            codes.append("duplicate_candidate")
        elif "temp/cache/log" in lowered:
            codes.append("temp_cache_log")
    return codes or ["low_confidence"]


def _normalize_duplicate_name(path_value: str) -> str:
    path_obj = Path(path_value)
    stem = path_obj.stem.lower()
    return re.sub(r"([_-](copy|\d+|[a-z]))+$", "", stem)


def _hash_file(path_obj: Path, *, chunk_size: int = 1024 * 1024) -> tuple[str | None, str | None]:
    digest = hashlib.sha256()
    try:
        stat_result = path_obj.stat()
        with path_obj.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                digest.update(chunk)
        with suppress(OSError):
            os.utime(path_obj, (stat_result.st_atime, stat_result.st_mtime))
    except OSError as exc:
        return None, f"hash unavailable: {exc}"
    return digest.hexdigest(), None


def _classify_duplicates(records: list[FolderScanRecord]) -> None:
    by_name: dict[str, list[FolderScanRecord]] = {}
    by_size: dict[int, list[FolderScanRecord]] = {}
    for record in records:
        normalized_name = _normalize_duplicate_name(record.path)
        by_name.setdefault(normalized_name, []).append(record)
        by_size.setdefault(record.size_bytes, []).append(record)

    by_hash: dict[tuple[int, str], list[FolderScanRecord]] = {}
    for size_bytes, grouped_records in by_size.items():
        if len(grouped_records) < 2:
            continue
        for record in grouped_records:
            file_hash, hash_error = _hash_file(Path(record.path))
            if hash_error:
                if not record.duplicate_reason:
                    record.duplicate_reason = hash_error
                continue
            if file_hash is not None:
                by_hash.setdefault((size_bytes, file_hash), []).append(record)

    for grouped_records in by_hash.values():
        if len(grouped_records) < 2:
            continue
        for record in grouped_records:
            record.duplicate_type = SAME_CONTENT_DUPLICATE
            reason = "duplicate candidate: same content hash and size match another file"
            record.duplicate_reason = reason
            if reason not in record.candidate_reasons:
                record.candidate_reasons.append(reason)

    normalized_names = list(by_name.items())
    for normalized_name, grouped_records in normalized_names:
        if len(grouped_records) > 1:
            for record in grouped_records:
                if record.duplicate_type == SAME_CONTENT_DUPLICATE:
                    continue
                record.duplicate_type = SAME_NAME_CANDIDATE
                reason = "duplicate candidate: same filename appears more than once"
                record.duplicate_reason = reason
                if reason not in record.candidate_reasons:
                    record.candidate_reasons.append(reason)

        for other_name, other_records in normalized_names:
            if normalized_name >= other_name:
                continue
            similarity = SequenceMatcher(None, normalized_name, other_name).ratio()
            if similarity < 0.7 and normalized_name not in other_name and other_name not in normalized_name:
                continue
            for record in grouped_records:
                if record.duplicate_type in {SAME_CONTENT_DUPLICATE, SAME_NAME_CANDIDATE}:
                    continue
                record.duplicate_type = SIMILAR_NAME_CANDIDATE
                reason = "duplicate candidate: filename is similar to another file"
                record.duplicate_reason = reason
                if reason not in record.candidate_reasons:
                    record.candidate_reasons.append(reason)
            for record in other_records:
                if record.duplicate_type in {SAME_CONTENT_DUPLICATE, SAME_NAME_CANDIDATE}:
                    continue
                record.duplicate_type = SIMILAR_NAME_CANDIDATE
                reason = "duplicate candidate: filename is similar to another file"
                record.duplicate_reason = reason
                if reason not in record.candidate_reasons:
                    record.candidate_reasons.append(reason)


def _extension_risk_score(suffix: str) -> float:
    if suffix in LOW_RISK_SUFFIXES:
        return 0.85
    if suffix in MANUAL_REVIEW_SUFFIXES:
        return 0.45
    if suffix in {".exe", ".dll", ".sys", ".bat", ".cmd", ".ps1"}:
        return 0.05
    return 0.55


def _score_candidate(
    *,
    name: str,
    suffix: str,
    days_since_access: int,
    size_bytes: int,
    stale_days: int,
    large_file_bytes: int,
    duplicate_count: int,
    reasons: list[str],
) -> tuple[float, str, float, float, float, float]:
    file_age_score = min(1.0, max(0.0, days_since_access / max(1, stale_days)))
    size_score = min(1.0, max(0.0, size_bytes / max(1, large_file_bytes)))
    duplicate_score = 1.0 if duplicate_count > 1 else 0.0
    extension_risk_score = _extension_risk_score(suffix)
    confidence = round(
        min(
            1.0,
            (0.35 * file_age_score)
            + (0.25 * size_score)
            + (0.2 * duplicate_score)
            + (0.2 * extension_risk_score),
        ),
        2,
    )
    lowered_name = name.lower()
    if any(token in lowered_name for token in DO_NOT_TOUCH_NAMES):
        return confidence, RiskLevel.DO_NOT_TOUCH.value, file_age_score, size_score, duplicate_score, extension_risk_score
    if confidence >= 0.72 and reasons:
        risk = RiskLevel.SAFE_TO_REVIEW.value
    elif reasons:
        risk = RiskLevel.NEEDS_MANUAL_CHECK.value
    else:
        risk = RiskLevel.DO_NOT_TOUCH.value
    return confidence, risk, file_age_score, size_score, duplicate_score, extension_risk_score


def _recommendation(reasons: list[str], risk_level: str) -> str:
    if not reasons:
        return Recommendation.DO_NOT_TOUCH.value
    if risk_level == RiskLevel.SAFE_TO_REVIEW.value:
        return Recommendation.SAFE_TO_REVIEW.value
    if risk_level == RiskLevel.NEEDS_MANUAL_CHECK.value:
        return Recommendation.NEEDS_MANUAL_CHECK.value
    return Recommendation.DO_NOT_TOUCH.value


def _operation_reason_text(record: dict[str, object]) -> str:
    reasons = string_list(record.get("candidate_reasons"))
    duplicate_type = str(record.get("duplicate_type") or "").strip()
    duplicate_reason = str(record.get("duplicate_reason") or "").strip()
    parts = reasons or ["Selected manually"]
    if duplicate_type:
        parts.append(f"duplicate type: {duplicate_type}")
    if duplicate_reason and duplicate_reason not in parts:
        parts.append(duplicate_reason)
    return ", ".join(parts)


def _apply_explainable_scoring(records: list[FolderScanRecord], *, stale_days: int, large_file_bytes: int) -> None:
    _classify_duplicates(records)
    name_counts: dict[str, int] = {}
    for record in records:
        duplicate_key = _normalize_duplicate_name(record.path)
        name_counts[duplicate_key] = name_counts.get(duplicate_key, 0) + 1

    for record in records:
        duplicate_key = _normalize_duplicate_name(record.path)
        duplicate_count = name_counts.get(duplicate_key, 0)
        (
            record.confidence,
            record.risk_level,
            record.file_age_score,
            record.size_score,
            record.duplicate_score,
            record.extension_risk_score,
        ) = _score_candidate(
            name=record.name,
            suffix=record.ext,
            days_since_access=record.days_since_access,
            size_bytes=record.size_bytes,
            stale_days=stale_days,
            large_file_bytes=large_file_bytes,
            duplicate_count=duplicate_count,
            reasons=record.candidate_reasons,
        )
        record.reason_codes = _reason_codes(record.candidate_reasons)
        record.category = record.duplicate_type or ("cleanup_candidate" if record.candidate_reasons else "keep")
        record.recommendation = _recommendation(record.candidate_reasons, record.risk_level)


def scan_local_folder(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int = 250 * 1024 * 1024,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    started = time.perf_counter()
    root = validate_scan_root_path(folder_path)
    records: list[FolderScanRecord] = []
    errors: list[str] = []
    now = datetime.datetime.now(datetime.UTC)
    stale_delta = datetime.timedelta(days=max(0, int(stale_days)))
    scanned = 0
    visited = 0

    def append_record(path_obj: Path, stat_result: os.stat_result) -> None:
        nonlocal scanned
        mtime = datetime.datetime.fromtimestamp(stat_result.st_mtime, tz=datetime.UTC)
        atime = datetime.datetime.fromtimestamp(stat_result.st_atime, tz=datetime.UTC)
        age_days = int((now - max(mtime, atime)).days)
        stale_age_days = (
            age_days
            if stale_days == 0 or (stale_days > 0 and (now - max(mtime, atime)) >= stale_delta)
            else None
        )
        reasons = _candidate_reasons(
            int(stat_result.st_size),
            stale_age_days,
            int(large_file_bytes),
            suffix=path_obj.suffix.lower(),
        )
        records.append(
            FolderScanRecord(
                path=str(path_obj),
                name=path_obj.name,
                ext=path_obj.suffix.lower(),
                size_bytes=int(stat_result.st_size),
                mtime=mtime.isoformat(),
                atime=atime.isoformat(),
                days_since_access=age_days,
                file_kind=infer_local_file_kind(str(path_obj)),
                is_stale=stale_age_days is not None,
                is_large=int(stat_result.st_size) >= int(large_file_bytes),
                candidate_reasons=reasons,
                recommendation=Recommendation.DO_NOT_TOUCH.value,
            )
        )
        scanned += 1
        if progress_callback is not None:
            progress_callback(scanned, max_files)

    def on_walk_error(err: OSError) -> None:
        errors.append(f"Scan error: {err}")

    if recursive:
        walker = os.walk(str(root), topdown=True, onerror=on_walk_error)
        for dirpath, dirnames, filenames in walker:
            dirnames[:] = [name for name in dirnames if name != QUARANTINE_DIRNAME]
            for filename in filenames:
                if scanned >= int(max_files):
                    break
                path_obj = Path(dirpath) / filename
                visited += 1
                try:
                    append_record(path_obj, path_obj.stat())
                except PermissionError:
                    errors.append(f"Permission denied: {path_obj}")
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    errors.append(f"Failed to inspect {path_obj}: {exc}")
            if scanned >= int(max_files):
                break
    else:
        try:
            for entry in os.scandir(str(root)):
                if scanned >= int(max_files):
                    break
                if not entry.is_file():
                    continue
                visited += 1
                try:
                    append_record(Path(entry.path), entry.stat())
                except PermissionError:
                    errors.append(f"Permission denied: {entry.path}")
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    errors.append(f"Failed to inspect {entry.path}: {exc}")
        except PermissionError:
            errors.append(f"Permission denied: {root}")
        except OSError as exc:
            errors.append(f"Failed to scan {root}: {exc}")

    _apply_explainable_scoring(records, stale_days=int(stale_days), large_file_bytes=int(large_file_bytes))
    quarantine_items, manifest_warnings = load_quarantine_items_with_warnings(str(root))
    errors.extend(manifest_warnings)
    stats = FolderScanStats(
        scanned_files=scanned,
        visited_files=visited,
        total_bytes=sum(item.size_bytes for item in records),
        stale_candidates=sum(1 for item in records if item.is_stale),
        large_candidates=sum(1 for item in records if item.is_large),
        quarantine_files=len(quarantine_items),
    )
    return FolderScanResult(
        path=str(root),
        recursive=bool(recursive),
        max_files=int(max_files),
        stale_days=int(stale_days),
        large_file_bytes=int(large_file_bytes),
        scanned_at=iso_now(),
        elapsed_seconds=round(time.perf_counter() - started, 3),
        records=records,
        errors=errors[:50],
        stats=stats,
    ).to_dict()


def run_folder_organizer(
    scan_result: dict[str, object],
    selected_paths: list[str],
    *,
    dry_run: bool,
) -> dict[str, object]:
    root = _scan_root_path(scan_result)
    quarantine_root = quarantine_dir(root).resolve()
    records = {
        str(dict_object(item).get("path")): dict_object(item)
        for item in object_list(scan_result.get("records"))
    }
    operation_id = uuid.uuid4().hex
    results: list[FolderOperationRow] = []
    with quarantine_manifest_guard(root):
        manifest = recover_quarantine_manifest(str(root))
        manifest_items = [dict_object(item) for item in object_list(manifest.get("items"))]

        for selected_path in selected_paths:
            record = records.get(selected_path)
            if not record:
                results.append(
                    FolderOperationRow(
                        original_path=selected_path,
                        new_path=None,
                        status="FAILED",
                        reason="Not found in current scan result",
                        duplicate_type=None,
                        duplicate_reason=None,
                        file_size=0,
                        last_modified=None,
                        processed_at=iso_now(),
                        error_message="Selected file is not available in the current scan result.",
                        operation_id=operation_id,
                    )
                )
                continue

            original_path = Path(selected_path)
            reasons = _operation_reason_text(record)
            file_size = safe_int(record.get("size_bytes"))
            last_modified = record.get("mtime")
            if dry_run:
                try:
                    preview_destination = safe_destination(
                        build_quarantine_target_path(
                            root,
                            original_path,
                            quarantine_root,
                            operation_id,
                        )
                    )
                    results.append(
                        FolderOperationRow(
                            original_path=str(original_path),
                            new_path=str(preview_destination),
                            status="SKIPPED",
                            reason=reasons,
                            duplicate_type=str(record.get("duplicate_type") or "") or None,
                            duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                            file_size=file_size,
                            last_modified=str(last_modified) if last_modified is not None else None,
                            processed_at=iso_now(),
                            error_message="Dry-run preview only.",
                            operation_id=operation_id,
                        )
                    )
                except (FileNotFoundError, PermissionError, OSError, ValueError, RuntimeError) as exc:
                    results.append(
                        FolderOperationRow(
                            original_path=str(original_path),
                            new_path=None,
                            status="FAILED",
                            reason=reasons,
                            duplicate_type=str(record.get("duplicate_type") or "") or None,
                            duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                            file_size=file_size,
                            last_modified=str(last_modified) if last_modified is not None else None,
                            processed_at=iso_now(),
                            error_message=str(exc) or type(exc).__name__,
                            operation_id=operation_id,
                        )
                    )
                continue

            try:
                resolved_original = _validate_path_within_root(original_path, root, label="selected file")
                existing = _find_active_original(manifest_items, resolved_original)
                if existing is not None:
                    raise FileExistsError("File already has an active quarantine manifest entry.")
                if not resolved_original.exists():
                    raise FileNotFoundError("Source file no longer exists.")
                destination = build_quarantine_target_path(
                    root,
                    resolved_original,
                    quarantine_root,
                    operation_id,
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination = safe_destination(destination)
                manifest_item = {
                    "original_path": str(resolved_original),
                    "quarantine_path": str(destination),
                    "moved_at": iso_now(),
                    "file_size": file_size,
                    "reason": reasons,
                    "operation_id": operation_id,
                    "last_modified": last_modified,
                    "status": QuarantineStatus.MOVING.value,
                    "last_error": "",
                    "duplicate_type": str(record.get("duplicate_type") or ""),
                    "duplicate_reason": str(record.get("duplicate_reason") or ""),
                }
                manifest_items.append(manifest_item)
                manifest["items"] = manifest_items
                save_manifest(root, manifest)
                shutil.move(str(resolved_original), str(destination))
                manifest_item["status"] = QuarantineStatus.QUARANTINED.value
                manifest_item["last_error"] = ""
                manifest["items"] = manifest_items
                save_manifest(root, manifest)
                results.append(
                    FolderOperationRow(
                        original_path=str(resolved_original),
                        new_path=str(destination),
                        status="SUCCESS",
                        reason=reasons,
                        duplicate_type=str(record.get("duplicate_type") or "") or None,
                        duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                        file_size=file_size,
                        last_modified=str(last_modified) if last_modified is not None else None,
                        processed_at=iso_now(),
                        error_message=None,
                        operation_id=operation_id,
                    )
                )
            except (FileNotFoundError, PermissionError, OSError, ValueError, RuntimeError) as exc:
                for item in reversed(manifest_items):
                    if str(item.get("original_path") or "") == str(original_path) and str(item.get("status") or "") == QuarantineStatus.MOVING.value:
                        item["status"] = QuarantineStatus.FAILED.value
                        item["last_error"] = str(exc) or type(exc).__name__
                        manifest["items"] = manifest_items
                        save_manifest(root, manifest)
                        break
                results.append(
                    FolderOperationRow(
                        original_path=str(original_path),
                        new_path=None,
                        status="FAILED",
                        reason=reasons,
                        duplicate_type=str(record.get("duplicate_type") or "") or None,
                        duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                        file_size=file_size,
                        last_modified=str(last_modified) if last_modified is not None else None,
                        processed_at=iso_now(),
                        error_message=str(exc) or type(exc).__name__,
                        operation_id=operation_id,
                    )
                )

    return FolderOperationResult(
        operation_id=operation_id,
        dry_run=dry_run,
        results=results,
        summary=FolderOperationSummary(
            selected=len(selected_paths),
            success=sum(1 for item in results if item.status == "SUCCESS"),
            failed=sum(1 for item in results if item.status == "FAILED"),
            skipped=sum(1 for item in results if item.status == "SKIPPED"),
        ),
    ).to_dict()


def list_quarantine_items(folder_path: str) -> list[dict[str, object]]:
    root = Path(folder_path).expanduser()
    with quarantine_manifest_guard(root):
        manifest = recover_quarantine_manifest(str(root))
        items = []
        for item in object_list(manifest.get("items")):
            item_dict = dict_object(item)
            if _is_active_manifest_item(item_dict):
                items.append(item_dict)
        return items


def restore_quarantined_items(folder_path: str, quarantine_paths: list[str]) -> dict[str, object]:
    root = Path(folder_path).expanduser()
    with quarantine_manifest_guard(root):
        manifest = recover_quarantine_manifest(str(root))
        items = [dict_object(item) for item in object_list(manifest.get("items"))]
        lookup = {str(item.get("quarantine_path")): item for item in items}
        results: list[FolderOperationRow] = []

        for quarantine_path in quarantine_paths:
            item = lookup.get(quarantine_path)
            if item is None:
                results.append(
                    FolderOperationRow(
                        original_path=None,
                        new_path=None,
                        status="FAILED",
                        reason="Manifest entry not found",
                        duplicate_type=None,
                        duplicate_reason=None,
                        file_size=0,
                        last_modified=None,
                        processed_at=iso_now(),
                        error_message="Manifest entry not found.",
                        operation_id=None,
                    )
                )
                continue
            source = Path(str(item.get("quarantine_path") or ""))
            original = Path(str(item.get("original_path") or ""))
            try:
                quarantine_root = quarantine_dir(root).resolve()
                validated_source = _validate_quarantine_path(source, quarantine_root, label="manifest quarantine_path")
                validated_original = _validate_path_within_root(original, root, label="manifest original_path")
                if not validated_source.exists():
                    raise FileNotFoundError("Quarantined file is missing.")
                destination = safe_destination(validated_original)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(validated_source), str(destination))
                item["status"] = QuarantineStatus.RESTORED.value
                item["restored_at"] = iso_now()
                item["restored_path"] = str(destination)
                results.append(
                    FolderOperationRow(
                        original_path=str(original),
                        new_path=str(destination),
                        status="SUCCESS",
                        reason=str(item.get("reason") or ""),
                        duplicate_type=str(item.get("duplicate_type") or "") or None,
                        duplicate_reason=str(item.get("duplicate_reason") or "") or None,
                        file_size=safe_int(item.get("file_size")),
                        last_modified=str(item.get("last_modified") or "") or None,
                        processed_at=iso_now(),
                        error_message=None,
                        operation_id=str(item.get("operation_id") or "") or None,
                    )
                )
            except (FileNotFoundError, PermissionError, OSError, ValueError, RuntimeError) as exc:
                results.append(
                    FolderOperationRow(
                        original_path=str(original) if item.get("original_path") else None,
                        new_path=None,
                        status="FAILED",
                        reason=str(item.get("reason") or ""),
                        duplicate_type=str(item.get("duplicate_type") or "") or None,
                        duplicate_reason=str(item.get("duplicate_reason") or "") or None,
                        file_size=safe_int(item.get("file_size")),
                        last_modified=str(item.get("last_modified") or "") or None,
                        processed_at=iso_now(),
                        error_message=str(exc) or type(exc).__name__,
                        operation_id=str(item.get("operation_id") or "") or None,
                    )
                )

        manifest["items"] = items
        save_manifest(root, manifest)
    return FolderOperationResult(
        operation_id=None,
        dry_run=False,
        results=results,
        summary=FolderOperationSummary(
            selected=len(quarantine_paths),
            success=sum(1 for item in results if item.status == "SUCCESS"),
            failed=sum(1 for item in results if item.status == "FAILED"),
            skipped=0,
        ),
    ).to_dict()
