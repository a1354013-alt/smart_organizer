from __future__ import annotations

import datetime
import hashlib
import os
import re
import shutil
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from contextlib import suppress
from difflib import SequenceMatcher
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

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
from malware_scanner import (
    ClamAvStatus,
    get_clamav_status,
    is_malware_blocked_status,
    scan_files,
)
from path_utils import canonical_path_key, paths_refer_to_same_location

LOW_RISK_SUFFIXES = {".txt", ".log", ".tmp", ".cache", ".bak", ".old", ".fake"}
MANUAL_REVIEW_SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
DO_NOT_TOUCH_NAMES = {"readme", "license", "copying", "important", "keep"}
SIMILAR_NAME_BUCKET_LIMIT = 80
SIMILAR_NAME_COMPARISON_LIMIT = 1500
SIMILAR_NAME_NEIGHBOR_LIMIT = 8
SAME_CONTENT_DUPLICATE = "same_content_duplicate"
SAME_NAME_CANDIDATE = "same_name_candidate"
SIMILAR_NAME_CANDIDATE = "similar_name_candidate"
INFECTED_FILE_BLOCK_MESSAGE = (
    "This file was marked infected by ClamAV. Smart Organizer will not move, delete, or open it. "
    "Please handle it with your antivirus software."
)
MALWARE_FILE_BLOCK_MESSAGE = (
    "This file does not have a confirmed clean malware scan status. "
    "Smart Organizer will skip it until the scan status is clean."
)
SYMLINK_BLOCK_MESSAGE = (
    "This path is a symbolic link. Smart Organizer skips symlinks by default for safety."
)
LARGE_FILE_DEEP_COMPARE_MESSAGE = (
    "Large-file duplicate hashing was skipped. Enable deep compare to verify same-content duplicates."
)


if TYPE_CHECKING:
    class OperationMalwarePayload(TypedDict):
        malware_status: str
        malware_verdict: str
        malware_scan_health: str
        malware_scanner: str
        malware_backend: str
        malware_engine_version: str
        malware_database_version: str
        malware_database_date: str
        malware_threat_name: str
        malware_message: str
        malware_scanned_at: str
        malware_cache_hit: bool
        malware_policy_name: str
        malware_policy_version: str
        malware_file_sha256: str
        malware_file_size: int
        malware_file_mtime_ns: int
        malware_file_inode: str


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


def _matches_scan_snapshot(path_obj: Path, *, expected_size: int, expected_mtime: object) -> bool:
    try:
        stat_result = path_obj.stat()
    except OSError:
        return False
    actual_mtime = datetime.datetime.fromtimestamp(stat_result.st_mtime, tz=datetime.UTC).isoformat()
    return int(stat_result.st_size) == int(expected_size) and str(actual_mtime) == str(expected_mtime)


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
    resolved = canonical_path_key(original_path)
    for item in manifest_items:
        if _is_active_manifest_item(item) and canonical_path_key(str(item.get("original_path") or "")) == resolved:
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


def _classify_duplicates(
    records: list[FolderScanRecord],
    *,
    large_file_bytes: int,
    deep_compare_large_files: bool,
) -> list[str]:
    def assign_group_id(grouped_records: list[FolderScanRecord], duplicate_type: str) -> str:
        key_material = "|".join(sorted(canonical_path_key(record.path) for record in grouped_records))
        return hashlib.sha256(f"{duplicate_type}|{key_material}".encode("utf-8")).hexdigest()[:16]

    notes: list[str] = []
    by_name: dict[str, list[FolderScanRecord]] = {}
    by_size: dict[int, list[FolderScanRecord]] = {}
    for record in records:
        if record.is_symlink:
            continue
        exact_name = Path(record.path).name.lower()
        by_name.setdefault(exact_name, []).append(record)
        by_size.setdefault(record.size_bytes, []).append(record)

    by_hash: dict[tuple[int, str], list[FolderScanRecord]] = {}
    for size_bytes, grouped_records in by_size.items():
        if len(grouped_records) < 2:
            continue
        for record in grouped_records:
            if record.size_bytes >= int(large_file_bytes) and not deep_compare_large_files:
                if LARGE_FILE_DEEP_COMPARE_MESSAGE not in record.candidate_reasons:
                    record.candidate_reasons.append(LARGE_FILE_DEEP_COMPARE_MESSAGE)
                if not record.duplicate_reason:
                    record.duplicate_reason = LARGE_FILE_DEEP_COMPARE_MESSAGE
                notes.append(LARGE_FILE_DEEP_COMPARE_MESSAGE)
                continue
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
        group_id = assign_group_id(grouped_records, SAME_CONTENT_DUPLICATE)
        for record in grouped_records:
            record.duplicate_type = SAME_CONTENT_DUPLICATE
            reason = "duplicate candidate: same content hash and size match another file"
            record.duplicate_reason = reason
            record.duplicate_group_id = group_id
            if reason not in record.candidate_reasons:
                record.candidate_reasons.append(reason)

    for grouped_records in by_name.values():
        if len(grouped_records) > 1:
            group_id = assign_group_id(grouped_records, SAME_NAME_CANDIDATE)
            for record in grouped_records:
                if record.duplicate_type == SAME_CONTENT_DUPLICATE:
                    continue
                record.duplicate_type = SAME_NAME_CANDIDATE
                reason = "duplicate candidate: same filename appears more than once"
                record.duplicate_reason = reason
                record.duplicate_group_id = group_id
                if reason not in record.candidate_reasons:
                    record.candidate_reasons.append(reason)
    return list(dict.fromkeys(notes))


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


def _risk_rank(value: str) -> int:
    ranks = {
        RiskLevel.SAFE_TO_REVIEW.value: 0,
        RiskLevel.NEEDS_MANUAL_CHECK.value: 1,
        RiskLevel.DO_NOT_TOUCH.value: 2,
    }
    return ranks.get(value, 2)


def _set_minimum_risk(record: FolderScanRecord, risk_level: str) -> None:
    if _risk_rank(risk_level) > _risk_rank(record.risk_level):
        record.risk_level = risk_level
    record.recommendation = _recommendation(record.candidate_reasons, record.risk_level)


def _apply_malware_scan_results(
    records: list[FolderScanRecord],
    *,
    timeout_seconds: int,
    max_database_age_days: int,
    policy_name: str = "standard",
    policy_version: str = "standard-v1",
) -> list[str]:
    notes: list[str] = []
    candidate_records = [record for record in records if record.candidate_reasons and not record.is_symlink]
    clamav_status: ClamAvStatus = get_clamav_status(max_database_age_days)
    if clamav_status.message:
        notes.append(f"ClamAV: {clamav_status.message}")
    if not candidate_records:
        return notes

    results = scan_files(
        [Path(record.path) for record in candidate_records],
        timeout_seconds=timeout_seconds,
        max_database_age_days=max_database_age_days,
        max_files=len(candidate_records),
    )
    for record in candidate_records:
        scan_result = results.get(str(Path(record.path).expanduser().resolve(strict=False)))
        if scan_result is None:
            continue
        record.malware_status = scan_result.status
        record.malware_verdict = scan_result.verdict
        record.malware_scan_health = scan_result.scan_health
        record.malware_scanner = scan_result.scanner
        record.malware_backend = scan_result.backend
        record.malware_engine_version = scan_result.engine_version or ""
        record.malware_database_version = scan_result.database_version or ""
        record.malware_database_date = scan_result.database_date or ""
        record.malware_threat_name = scan_result.threat_name or ""
        record.malware_message = scan_result.message
        record.malware_scanned_at = iso_now()
        record.malware_cache_hit = bool(scan_result.cache_hit)
        record.malware_policy_name = policy_name
        record.malware_policy_version = policy_version
        record.malware_file_sha256 = scan_result.file_sha256 or ""
        record.malware_file_size = safe_int(scan_result.file_size)
        record.malware_file_mtime_ns = safe_int(scan_result.file_mtime_ns)
        record.malware_file_inode = scan_result.file_inode or ""
        if scan_result.status in {
            "infected",
            "suspicious",
            "timeout",
            "error",
            "scanner_unavailable",
            "database_missing",
        }:
            _set_minimum_risk(record, RiskLevel.DO_NOT_TOUCH.value)
        elif scan_result.status == "database_outdated":
            _set_minimum_risk(record, RiskLevel.NEEDS_MANUAL_CHECK.value)
    return notes


def _operation_malware_payload(record: dict[str, object]) -> OperationMalwarePayload:
    return {
        "malware_status": str(record.get("malware_status") or "not_scanned"),
        "malware_verdict": str(record.get("malware_verdict") or record.get("malware_status") or "not_scanned"),
        "malware_scan_health": str(record.get("malware_scan_health") or "incomplete"),
        "malware_scanner": str(record.get("malware_scanner") or ""),
        "malware_backend": str(record.get("malware_backend") or ""),
        "malware_engine_version": str(record.get("malware_engine_version") or ""),
        "malware_database_version": str(record.get("malware_database_version") or ""),
        "malware_database_date": str(record.get("malware_database_date") or ""),
        "malware_threat_name": str(record.get("malware_threat_name") or ""),
        "malware_message": str(record.get("malware_message") or ""),
        "malware_scanned_at": str(record.get("malware_scanned_at") or ""),
        "malware_cache_hit": bool(record.get("malware_cache_hit")),
        "malware_policy_name": str(record.get("malware_policy_name") or ""),
        "malware_policy_version": str(record.get("malware_policy_version") or ""),
        "malware_file_sha256": str(record.get("malware_file_sha256") or ""),
        "malware_file_size": safe_int(record.get("malware_file_size")),
        "malware_file_mtime_ns": safe_int(record.get("malware_file_mtime_ns")),
        "malware_file_inode": str(record.get("malware_file_inode") or ""),
    }


def _matches_malware_snapshot(path_obj: Path, record: dict[str, object]) -> bool:
    expected_size = safe_int(record.get("malware_file_size"))
    expected_mtime_ns = safe_int(record.get("malware_file_mtime_ns"))
    expected_inode = str(record.get("malware_file_inode") or "").strip()
    expected_sha256 = str(record.get("malware_file_sha256") or "").strip()
    try:
        stat_result = path_obj.stat()
    except OSError:
        return False
    if expected_size and int(stat_result.st_size) != expected_size:
        return False
    if expected_mtime_ns and int(getattr(stat_result, "st_mtime_ns", 0)) != expected_mtime_ns:
        return False
    current_inode = f"{getattr(stat_result, 'st_dev', 0)}:{getattr(stat_result, 'st_ino', 0)}"
    if expected_inode and current_inode != expected_inode:
        return False
    if expected_sha256:
        current_sha256, hash_error = _hash_file(path_obj)
        if hash_error is not None or current_sha256 != expected_sha256:
            return False
    return True


def _malware_clean_verdict_is_compatible(record: dict[str, object]) -> tuple[bool, str]:
    current_status = cast(ClamAvStatus | None, record.get("_current_clamav_status"))
    current_policy_version = str(record.get("_active_malware_policy_version") or "").strip()
    scan_health = str(record.get("malware_scan_health") or "").strip() or "incomplete"
    status = str(record.get("malware_status") or "").strip() or "not_scanned"
    if current_status is None or current_status.availability != "available":
        message = current_status.message if current_status is not None else "Scanner status unavailable."
        return False, f"{MALWARE_FILE_BLOCK_MESSAGE} {message}".strip()
    if scan_health != "ok" or status != "clean":
        message = str(record.get("malware_message") or "").strip()
        return False, f"{MALWARE_FILE_BLOCK_MESSAGE} {message}".strip()
    if current_policy_version and str(record.get("malware_policy_version") or "").strip() != current_policy_version:
        return False, "Malware policy changed after the clean verdict. Re-run the malware scan before continuing."
    database_version = str(record.get("malware_database_version") or "").strip()
    database_date = str(record.get("malware_database_date") or "").strip()
    if database_version != str(current_status.database_version or "").strip() or database_date != str(
        current_status.database_date or ""
    ).strip():
        return False, "Malware database changed after the clean verdict. Re-run the malware scan before continuing."
    return True, ""


def _malware_block_message(record: dict[str, object]) -> str | None:
    status = str(record.get("malware_status") or "")
    enforce_malware_scan = bool(record.get("_enable_malware_scan"))
    if not is_malware_blocked_status(status, enable_malware_scan=enforce_malware_scan):
        if not enforce_malware_scan:
            return None
        compatible, message = _malware_clean_verdict_is_compatible(record)
        if not compatible:
            return message
        malware_path = str(record.get("_malware_validation_path") or record.get("path") or "").strip()
        if malware_path and not _matches_malware_snapshot(Path(malware_path), record):
            return "File content or identity changed after the clean malware verdict. Re-run the malware scan before continuing."
        return None
    if status == "infected":
        return INFECTED_FILE_BLOCK_MESSAGE
    message = str(record.get("malware_message") or "").strip()
    return f"{MALWARE_FILE_BLOCK_MESSAGE} {message}".strip()


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
    name_counts: dict[str, int] = {}
    for record in records:
        if record.is_symlink:
            continue
        duplicate_key = _normalize_duplicate_name(record.path)
        name_counts[duplicate_key] = name_counts.get(duplicate_key, 0) + 1

    for record in records:
        if record.is_symlink:
            record.confidence = 0.0
            record.risk_level = RiskLevel.DO_NOT_TOUCH.value
            record.reason_codes = _reason_codes(record.candidate_reasons)
            record.category = "symlink"
            record.recommendation = Recommendation.DO_NOT_TOUCH.value
            continue
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


def _normalized_name_token(value: str) -> str:
    stem = Path(value or "").stem.lower()
    normalized = re.sub(r"(?i)(copy|副本)$", "", stem)
    normalized = re.sub(r"[_\-\s]?\d+$", "", normalized)
    normalized = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", normalized)
    return normalized or stem or "file"


def _similar_name_bucket_key(record: FolderScanRecord) -> tuple[str, str, int]:
    normalized = _normalized_name_token(record.name)
    prefix = normalized[:6]
    size_bucket = record.size_bytes // max(1, 256 * 1024)
    return (record.ext, prefix, size_bucket)


def _looks_similar_name(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    common_prefix = os.path.commonprefix([left, right])
    min_len = max(3, min(len(left), len(right)))
    if len(common_prefix) >= min_len - 1:
        return True
    similarity = SequenceMatcher(None, left, right).ratio()
    return similarity >= 0.7 or left in right or right in left


def _apply_similar_name_detection(records: list[FolderScanRecord]) -> list[str]:
    notes: list[str] = []
    buckets: dict[tuple[str, str, int], list[FolderScanRecord]] = defaultdict(list)
    similar_edges: dict[str, set[str]] = defaultdict(set)
    record_lookup: dict[str, FolderScanRecord] = {}
    for record in records:
        if record.is_symlink:
            continue
        if record.duplicate_type == SAME_CONTENT_DUPLICATE:
            continue
        record_lookup[canonical_path_key(record.path)] = record
        buckets[_similar_name_bucket_key(record)].append(record)

    comparisons = 0
    skipped_buckets = 0
    for bucket_records in buckets.values():
        if len(bucket_records) < 2:
            continue
        if len(bucket_records) > SIMILAR_NAME_BUCKET_LIMIT:
            skipped_buckets += 1
            bucket_records = bucket_records[:SIMILAR_NAME_BUCKET_LIMIT]
        ordered = sorted(bucket_records, key=lambda item: _normalized_name_token(item.name))
        for index, record in enumerate(ordered):
            base_name = _normalized_name_token(record.name)
            for candidate in ordered[index + 1 : index + 1 + SIMILAR_NAME_NEIGHBOR_LIMIT]:
                if comparisons >= SIMILAR_NAME_COMPARISON_LIMIT:
                    notes.append(
                        "Similar-name detection reached its comparison limit and skipped some expensive checks."
                    )
                    return notes
                comparisons += 1
                candidate_name = _normalized_name_token(candidate.name)
                if _looks_similar_name(base_name, candidate_name):
                    reason = "duplicate candidate: filename is similar to another file"
                    left_key = canonical_path_key(record.path)
                    right_key = canonical_path_key(candidate.path)
                    similar_edges[left_key].add(right_key)
                    similar_edges[right_key].add(left_key)
                    if record.duplicate_type != SAME_NAME_CANDIDATE:
                        record.duplicate_type = SIMILAR_NAME_CANDIDATE
                        record.duplicate_reason = reason
                        if reason not in record.candidate_reasons:
                            record.candidate_reasons.append(reason)
                    if candidate.duplicate_type != SAME_NAME_CANDIDATE:
                        candidate.duplicate_type = SIMILAR_NAME_CANDIDATE
                        candidate.duplicate_reason = reason
                        if reason not in candidate.candidate_reasons:
                            candidate.candidate_reasons.append(reason)
    if skipped_buckets:
        notes.append(
            f"Similar-name detection skipped {skipped_buckets} oversized bucket(s) to keep large scans responsive."
        )
    visited: set[str] = set()
    for start_key, neighbors in similar_edges.items():
        if start_key in visited or not neighbors:
            continue
        stack = [start_key]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(sorted(similar_edges.get(current, set()) - visited))
        if len(component) < 2:
            continue
        group_id = hashlib.sha256(
            f"{SIMILAR_NAME_CANDIDATE}|{'|'.join(sorted(component))}".encode("utf-8")
        ).hexdigest()[:16]
        for key in component:
            record = record_lookup.get(key)
            if record is not None and record.duplicate_type == SIMILAR_NAME_CANDIDATE:
                record.duplicate_group_id = group_id
    return notes


def scan_local_folder(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int = 250 * 1024 * 1024,
    deep_compare_large_files: bool = False,
    enable_malware_scan: bool = False,
    malware_scan_timeout_seconds: int = 30,
    malware_database_max_age_days: int = 7,
    malware_scan_policy: str = "standard",
    malware_scan_policy_version: str = "standard-v1",
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    started = time.perf_counter()
    root = validate_scan_root_path(folder_path)
    records: list[FolderScanRecord] = []
    errors: list[str] = []
    notes: list[str] = []
    now = datetime.datetime.now(datetime.UTC)
    stale_delta = datetime.timedelta(days=max(0, int(stale_days)))
    scanned = 0
    visited = 0
    limit_reached = False

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
                is_symlink=False,
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
            kept_dirnames: list[str] = []
            for name in dirnames:
                if name == QUARANTINE_DIRNAME:
                    continue
                dir_path = Path(dirpath) / name
                try:
                    if dir_path.is_symlink():
                        notes.append(f"Skipped symlink directory for safety: {dir_path}")
                        continue
                except OSError:
                    notes.append(f"Skipped unreadable directory entry: {dir_path}")
                    continue
                kept_dirnames.append(name)
            dirnames[:] = kept_dirnames
            for filename in filenames:
                if scanned >= int(max_files):
                    limit_reached = True
                    break
                path_obj = Path(dirpath) / filename
                visited += 1
                try:
                    stat_result = path_obj.lstat()
                    if path_obj.is_symlink():
                        records.append(
                            FolderScanRecord(
                                path=str(path_obj),
                                name=path_obj.name,
                                ext=path_obj.suffix.lower(),
                                size_bytes=int(stat_result.st_size),
                                mtime=datetime.datetime.fromtimestamp(stat_result.st_mtime, tz=datetime.UTC).isoformat(),
                                atime=datetime.datetime.fromtimestamp(stat_result.st_atime, tz=datetime.UTC).isoformat(),
                                days_since_access=0,
                                file_kind=infer_local_file_kind(str(path_obj)),
                                is_symlink=True,
                                is_stale=False,
                                is_large=False,
                                candidate_reasons=[SYMLINK_BLOCK_MESSAGE],
                                recommendation=Recommendation.DO_NOT_TOUCH.value,
                                category="symlink",
                                duplicate_reason=SYMLINK_BLOCK_MESSAGE,
                                risk_level=RiskLevel.DO_NOT_TOUCH.value,
                            )
                        )
                        scanned += 1
                        continue
                    append_record(path_obj, stat_result)
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
                    limit_reached = True
                    break
                try:
                    if entry.is_symlink():
                        stat_result = entry.stat(follow_symlinks=False)
                        records.append(
                            FolderScanRecord(
                                path=str(Path(entry.path)),
                                name=entry.name,
                                ext=Path(entry.name).suffix.lower(),
                                size_bytes=int(stat_result.st_size),
                                mtime=datetime.datetime.fromtimestamp(stat_result.st_mtime, tz=datetime.UTC).isoformat(),
                                atime=datetime.datetime.fromtimestamp(stat_result.st_atime, tz=datetime.UTC).isoformat(),
                                days_since_access=0,
                                file_kind=infer_local_file_kind(entry.path),
                                is_symlink=True,
                                is_stale=False,
                                is_large=False,
                                candidate_reasons=[SYMLINK_BLOCK_MESSAGE],
                                recommendation=Recommendation.DO_NOT_TOUCH.value,
                                category="symlink",
                                duplicate_reason=SYMLINK_BLOCK_MESSAGE,
                                risk_level=RiskLevel.DO_NOT_TOUCH.value,
                            )
                        )
                        scanned += 1
                        continue
                except OSError:
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                visited += 1
                try:
                    append_record(Path(entry.path), entry.stat(follow_symlinks=False))
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

    duplicate_notes = _classify_duplicates(
        records,
        large_file_bytes=int(large_file_bytes),
        deep_compare_large_files=bool(deep_compare_large_files),
    )
    _apply_explainable_scoring(records, stale_days=int(stale_days), large_file_bytes=int(large_file_bytes))
    notes.extend(duplicate_notes)
    notes.extend(_apply_similar_name_detection(records))
    if enable_malware_scan:
        notes.extend(
            _apply_malware_scan_results(
                records,
                timeout_seconds=int(malware_scan_timeout_seconds),
                max_database_age_days=int(malware_database_max_age_days),
                policy_name=str(malware_scan_policy or "standard"),
                policy_version=str(malware_scan_policy_version or "standard-v1"),
            )
        )
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
        enable_malware_scan=bool(enable_malware_scan),
        malware_scan_policy=str(malware_scan_policy or "standard"),
        malware_scan_policy_version=str(malware_scan_policy_version or "standard-v1"),
        limit_reached=limit_reached,
        scanned_at=iso_now(),
        elapsed_seconds=round(time.perf_counter() - started, 3),
        records=records,
        errors=errors[:50],
        notes=notes[:20],
        stats=stats,
        analysis_settings=None,
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
        canonical_path_key(str(dict_object(item).get("path") or "")): dict_object(item)
        for item in object_list(scan_result.get("records"))
        if str(dict_object(item).get("path") or "").strip()
    }
    operation_id = uuid.uuid4().hex
    results: list[FolderOperationRow] = []
    enable_malware_scan = bool(scan_result.get("enable_malware_scan"))
    current_clamav_status = get_clamav_status(
        max(1, safe_int(scan_result.get("malware_database_max_age_days") or 7))
    ) if enable_malware_scan else None
    with quarantine_manifest_guard(root):
        manifest = recover_quarantine_manifest(str(root))
        manifest_items = [dict_object(item) for item in object_list(manifest.get("items"))]

        for selected_path in selected_paths:
            selected_key = canonical_path_key(selected_path)
            record = records.get(selected_key)
            if not record:
                results.append(
                    FolderOperationRow(
                        original_path=selected_path,
                        new_path=None,
                        status="FAILED",
                        reason="Not found in current scan result",
                        duplicate_type=None,
                        duplicate_reason=None,
                        duplicate_group_id=None,
                        file_size=0,
                        last_modified=None,
                        processed_at=iso_now(),
                        error_message="Selected file is not available in the current scan result.",
                        operation_id=operation_id,
                        **_operation_malware_payload({}),
                    )
                )
                continue

            original_path = Path(selected_path)
            display_original_path = str(record.get("path") or selected_path)
            reasons = _operation_reason_text(record)
            file_size = safe_int(record.get("size_bytes"))
            last_modified = record.get("mtime")
            malware_payload = _operation_malware_payload(record)
            record_with_policy = dict(record)
            record_with_policy["_enable_malware_scan"] = enable_malware_scan
            record_with_policy["_active_malware_policy_version"] = str(
                scan_result.get("malware_scan_policy_version") or ""
            )
            record_with_policy["_current_clamav_status"] = current_clamav_status
            record_with_policy["_malware_validation_path"] = str(record.get("path") or selected_path)
            malware_block_message = _malware_block_message(record_with_policy)
            if bool(record.get("is_symlink")):
                malware_block_message = SYMLINK_BLOCK_MESSAGE
            if malware_block_message is not None:
                results.append(
                    FolderOperationRow(
                        original_path=display_original_path,
                        new_path=None,
                        status="SKIPPED",
                        reason=reasons,
                        duplicate_type=str(record.get("duplicate_type") or "") or None,
                        duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                        duplicate_group_id=str(record.get("duplicate_group_id") or "") or None,
                        file_size=file_size,
                        last_modified=str(last_modified) if last_modified is not None else None,
                        processed_at=iso_now(),
                        error_message=malware_block_message,
                        operation_id=operation_id,
                        **malware_payload,
                    )
                )
                continue
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
                            original_path=display_original_path,
                            new_path=str(preview_destination),
                            status="PREVIEW",
                            reason=reasons,
                            duplicate_type=str(record.get("duplicate_type") or "") or None,
                            duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                            duplicate_group_id=str(record.get("duplicate_group_id") or "") or None,
                            file_size=file_size,
                            last_modified=str(last_modified) if last_modified is not None else None,
                            processed_at=iso_now(),
                            error_message="Dry-run preview only.",
                            operation_id=operation_id,
                            **malware_payload,
                        )
                    )
                except (FileNotFoundError, PermissionError, OSError, ValueError, RuntimeError) as exc:
                    results.append(
                        FolderOperationRow(
                            original_path=display_original_path,
                            new_path=None,
                            status="FAILED",
                            reason=reasons,
                            duplicate_type=str(record.get("duplicate_type") or "") or None,
                            duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                            duplicate_group_id=str(record.get("duplicate_group_id") or "") or None,
                            file_size=file_size,
                            last_modified=str(last_modified) if last_modified is not None else None,
                            processed_at=iso_now(),
                            error_message=str(exc) or type(exc).__name__,
                            operation_id=operation_id,
                            **malware_payload,
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
                if not _matches_scan_snapshot(
                    resolved_original,
                    expected_size=file_size,
                    expected_mtime=last_modified,
                ):
                    raise RuntimeError("Selected file changed after scan. Re-run malware scan and folder scan before quarantine.")
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
                    "duplicate_group_id": str(record.get("duplicate_group_id") or ""),
                    "malware_status": malware_payload["malware_status"],
                    "malware_scanner": malware_payload["malware_scanner"],
                    "malware_threat_name": malware_payload["malware_threat_name"],
                    "malware_message": malware_payload["malware_message"],
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
                        original_path=display_original_path,
                        new_path=str(destination),
                        status="SUCCESS",
                        reason=reasons,
                        duplicate_type=str(record.get("duplicate_type") or "") or None,
                        duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                        duplicate_group_id=str(record.get("duplicate_group_id") or "") or None,
                        file_size=file_size,
                        last_modified=str(last_modified) if last_modified is not None else None,
                        processed_at=iso_now(),
                        error_message=None,
                        operation_id=operation_id,
                        **malware_payload,
                    )
                )
            except (FileNotFoundError, PermissionError, OSError, ValueError, RuntimeError) as exc:
                for item in reversed(manifest_items):
                    if (
                        str(item.get("status") or "") == QuarantineStatus.MOVING.value
                        and paths_refer_to_same_location(str(item.get("original_path") or ""), original_path)
                    ):
                        item["status"] = QuarantineStatus.FAILED.value
                        item["last_error"] = str(exc) or type(exc).__name__
                        manifest["items"] = manifest_items
                        save_manifest(root, manifest)
                        break
                results.append(
                    FolderOperationRow(
                        original_path=display_original_path,
                        new_path=None,
                        status="FAILED",
                        reason=reasons,
                        duplicate_type=str(record.get("duplicate_type") or "") or None,
                        duplicate_reason=str(record.get("duplicate_reason") or "") or None,
                        duplicate_group_id=str(record.get("duplicate_group_id") or "") or None,
                        file_size=file_size,
                        last_modified=str(last_modified) if last_modified is not None else None,
                        processed_at=iso_now(),
                        error_message=str(exc) or type(exc).__name__,
                        operation_id=operation_id,
                        **malware_payload,
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
            preview=sum(1 for item in results if item.status == "PREVIEW"),
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
        lookup = {
            canonical_path_key(str(item.get("quarantine_path") or "")): item
            for item in items
            if str(item.get("quarantine_path") or "").strip()
        }
        results: list[FolderOperationRow] = []

        for quarantine_path in quarantine_paths:
            item = lookup.get(canonical_path_key(quarantine_path))
            if item is None:
                results.append(
                    FolderOperationRow(
                        original_path=None,
                        new_path=None,
                        status="FAILED",
                        reason="Manifest entry not found",
                        duplicate_type=None,
                        duplicate_reason=None,
                        duplicate_group_id=None,
                        file_size=0,
                        last_modified=None,
                        processed_at=iso_now(),
                        error_message="Manifest entry not found.",
                        operation_id=None,
                        **_operation_malware_payload({}),
                    )
                )
                continue
            source = Path(str(item.get("quarantine_path") or ""))
            original = Path(str(item.get("original_path") or ""))
            malware_payload = _operation_malware_payload(item)
            current_clamav_status = get_clamav_status(
                max(1, safe_int(item.get("malware_database_max_age_days") or 7))
            ) if str(item.get("malware_policy_version") or "").strip() else None
            item_with_policy = dict(item)
            item_with_policy["_enable_malware_scan"] = bool(str(item.get("malware_policy_version") or "").strip())
            item_with_policy["_active_malware_policy_version"] = str(item.get("malware_policy_version") or "")
            item_with_policy["_current_clamav_status"] = current_clamav_status
            item_with_policy["_malware_validation_path"] = str(item.get("quarantine_path") or "")
            malware_block_message = _malware_block_message(item_with_policy)
            if malware_block_message is not None:
                results.append(
                    FolderOperationRow(
                        original_path=str(original) if item.get("original_path") else None,
                        new_path=None,
                        status="FAILED",
                        reason=str(item.get("reason") or ""),
                        duplicate_type=str(item.get("duplicate_type") or "") or None,
                        duplicate_reason=str(item.get("duplicate_reason") or "") or None,
                        duplicate_group_id=str(item.get("duplicate_group_id") or "") or None,
                        file_size=safe_int(item.get("file_size")),
                        last_modified=str(item.get("last_modified") or "") or None,
                        processed_at=iso_now(),
                        error_message=malware_block_message,
                        operation_id=str(item.get("operation_id") or "") or None,
                        **malware_payload,
                    )
                )
                continue
            try:
                quarantine_root = quarantine_dir(root).resolve()
                validated_source = _validate_quarantine_path(source, quarantine_root, label="manifest quarantine_path")
                validated_original = _validate_path_within_root(original, root, label="manifest original_path")
                if not validated_source.exists():
                    raise FileNotFoundError("Quarantined file is missing.")
                if not _matches_scan_snapshot(
                    validated_source,
                    expected_size=safe_int(item.get("file_size")),
                    expected_mtime=item.get("last_modified"),
                ):
                    raise RuntimeError("Quarantined file changed after the original scan snapshot. Re-scan before restore.")
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
                        duplicate_group_id=str(item.get("duplicate_group_id") or "") or None,
                        file_size=safe_int(item.get("file_size")),
                        last_modified=str(item.get("last_modified") or "") or None,
                        processed_at=iso_now(),
                        error_message=None,
                        operation_id=str(item.get("operation_id") or "") or None,
                        **malware_payload,
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
                        duplicate_group_id=str(item.get("duplicate_group_id") or "") or None,
                        file_size=safe_int(item.get("file_size")),
                        last_modified=str(item.get("last_modified") or "") or None,
                        processed_at=iso_now(),
                        error_message=str(exc) or type(exc).__name__,
                        operation_id=str(item.get("operation_id") or "") or None,
                        **malware_payload,
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
