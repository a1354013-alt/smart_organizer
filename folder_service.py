from __future__ import annotations

import datetime
import os
import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Literal, TypedDict, cast

from folder_models import FolderActionResult, FolderOrganizerError, ScanPathError, safe_int
from folder_organizer import (
    FolderOrganizer,
    list_quarantine_items,
    load_quarantine_items_with_warnings,
    restore_quarantined_items,
    run_folder_organizer,
    scan_local_folder,
    validate_scan_root_path,
)
from malware_scanner import MalwareScanner, ScanPolicy
from path_utils import canonical_path_key

_FAST_SCAN_SUFFIXES = {
    ".7z",
    ".apk",
    ".bat",
    ".cab",
    ".cmd",
    ".com",
    ".dll",
    ".doc",
    ".docm",
    ".docx",
    ".exe",
    ".hta",
    ".iso",
    ".jar",
    ".js",
    ".lnk",
    ".msi",
    ".pdf",
    ".ppt",
    ".pptm",
    ".pptx",
    ".ps1",
    ".rar",
    ".rtf",
    ".scr",
    ".sh",
    ".vbs",
    ".xls",
    ".xlsb",
    ".xlsm",
    ".xlsx",
    ".zip",
}
_STANDARD_SKIP_SUFFIXES = {
    ".avi",
    ".bmp",
    ".flac",
    ".gif",
    ".heic",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".png",
    ".tif",
    ".tiff",
    ".wav",
    ".webm",
    ".webp",
    ".wmv",
}

MalwareResultSeverity = Literal["danger", "warning", "success"]


class MalwareScanSummary(TypedDict, total=False):
    scan_mode: str
    coverage_scope: str
    coverage_is_partial: bool
    total_files_considered: int
    enumerated_files: int
    result_records: int
    files_successfully_scanned: int
    completed_files: int
    clean_files: int
    suspicious_files: int
    infected_files: int
    not_scanned_files: int
    incomplete_files: int
    incomplete_or_failed_scans: int
    missing_result_files: int
    cache_hits: int
    files_sent_to_scanner: int
    permission_failures: int
    enumeration_errors: int
    skipped_symlinks: int
    scan_errors: int
    scanner_unavailable_files: int
    database_missing_files: int
    database_outdated_files: int
    timeout_files: int
    backend_error_files: int
    limit_exceeded_files: int
    mode_excluded_files: int
    limit_reached: bool
    total_bytes: int
    elapsed_seconds: float
    files_per_second: float
    bytes_per_second: float
    backend: str
    engine_version: str
    database_version: str
    database_date: str
    availability: str
    scanner_available: bool
    database_fresh: bool
    enumeration_incomplete: bool
    totals_consistent: bool
    overall_severity: MalwareResultSeverity
    overall_status: str


def malware_result_severity(summary: Mapping[str, object]) -> MalwareResultSeverity:
    if safe_int(summary.get("infected_files")) > 0:
        return "danger"

    warning_conditions = (
        safe_int(summary.get("suspicious_files")) > 0,
        safe_int(summary.get("incomplete_files")) > 0,
        safe_int(summary.get("not_scanned_files")) > 0,
        safe_int(summary.get("missing_result_files")) > 0,
        safe_int(summary.get("scanner_unavailable_files")) > 0,
        safe_int(summary.get("database_missing_files")) > 0,
        safe_int(summary.get("database_outdated_files")) > 0,
        safe_int(summary.get("timeout_files")) > 0,
        safe_int(summary.get("limit_exceeded_files")) > 0,
        safe_int(summary.get("backend_error_files")) > 0,
        safe_int(summary.get("permission_failures")) > 0,
        safe_int(summary.get("enumeration_errors")) > 0,
        bool(summary.get("limit_reached")),
        bool(summary.get("coverage_is_partial")),
        bool(summary.get("enumeration_incomplete")),
        safe_int(summary.get("mode_excluded_files")) > 0,
        not bool(summary.get("totals_consistent", True)),
        not bool(summary.get("database_fresh", True)),
        not bool(summary.get("scanner_available", True)),
    )
    if any(warning_conditions):
        return "warning"
    return "success"


def malware_result_conclusion_key(summary: Mapping[str, object]) -> str:
    severity = malware_result_severity(summary)
    if severity == "danger":
        return "home.malware_result.conclusion.infected"
    if safe_int(summary.get("suspicious_files")) > 0:
        return "home.malware_result.conclusion.suspicious"
    if severity == "warning":
        return "home.malware_result.conclusion.incomplete"
    return "home.malware_result.conclusion.clean"


def build_folder_organizer(scan_root: Path | str, quarantine_root: Path | str) -> FolderOrganizer:
    return FolderOrganizer(scan_root=scan_root, quarantine_root=quarantine_root)


def quarantine_many(
    organizer: FolderOrganizer,
    items: Iterable[tuple[Path | str, Path | str]],
) -> list[FolderActionResult]:
    return [organizer.quarantine_file(source, target) for source, target in items]


def restore_many(
    organizer: FolderOrganizer,
    items: Iterable[tuple[Path | str, Path | str]],
) -> list[FolderActionResult]:
    return [organizer.restore_file(source, target) for source, target in items]


def validate_scan_target(folder_path: str) -> Path:
    try:
        return validate_scan_root_path(folder_path)
    except ScanPathError as exc:
        message = str(exc)
        if message == "Enter a folder path first.":
            raise
        if "does not exist" in message:
            raise ScanPathError("The folder does not exist.") from exc
        if "not a directory" in message:
            raise ScanPathError("The path must point to a folder.") from exc
        raise


def _build_folder_scan_policy(*, policy_name: str, timeout_seconds: int) -> ScanPolicy:
    normalized_name = str(policy_name or "standard").strip().lower() or "standard"
    strict = normalized_name == "strict"
    return ScanPolicy(
        name=normalized_name,
        policy_version="strict-v1" if strict else "standard-v1",
        max_scan_time_seconds=max(1, int(timeout_seconds)),
        enable_pua=bool(strict),
        enable_heuristics=bool(strict),
        alert_encrypted=bool(strict),
        alert_broken_executables=bool(strict),
    )


def _iter_folder_files(
    root: Path,
    *,
    recursive: bool,
    max_files: int,
) -> tuple[list[dict[str, object]], list[str], list[str], int, dict[str, int | bool]]:
    records: list[dict[str, object]] = []
    errors: list[str] = []
    notes: list[str] = []
    visited = 0
    permission_failures = 0
    skipped_symlinks = 0
    enumeration_errors = 0
    limit_reached = False

    def append_record(path_obj: Path, stat_result: os.stat_result) -> None:
        nonlocal visited
        visited += 1
        records.append(
            {
                "path": str(path_obj),
                "relative_path": str(path_obj.relative_to(root)),
                "name": path_obj.name,
                "size_bytes": int(stat_result.st_size),
                "mtime": datetime.datetime.fromtimestamp(stat_result.st_mtime, tz=datetime.UTC).isoformat(),
                "mtime_ns": int(getattr(stat_result, "st_mtime_ns", 0)),
                "file_inode": f"{getattr(stat_result, 'st_dev', 0)}:{getattr(stat_result, 'st_ino', 0)}",
            }
        )

    if recursive:
        walker = os.walk(str(root), topdown=True)
        for dirpath, dirnames, filenames in walker:
            kept_dirnames: list[str] = []
            for name in dirnames:
                if name == ".smart_organizer_quarantine":
                    continue
                dir_path = Path(dirpath) / name
                try:
                    if dir_path.is_symlink():
                        skipped_symlinks += 1
                        notes.append(f"Skipped symlink directory for safety: {dir_path}")
                        continue
                except OSError:
                    enumeration_errors += 1
                    notes.append(f"Skipped unreadable directory entry: {dir_path}")
                    continue
                kept_dirnames.append(name)
            dirnames[:] = kept_dirnames
            for filename in filenames:
                if len(records) >= int(max_files):
                    limit_reached = True
                    break
                path_obj = Path(dirpath) / filename
                try:
                    stat_result = path_obj.lstat()
                    if path_obj.is_symlink():
                        skipped_symlinks += 1
                        notes.append(f"Skipped symlink file for safety: {path_obj}")
                        continue
                    append_record(path_obj, stat_result)
                except PermissionError:
                    permission_failures += 1
                    errors.append(f"Permission denied: {path_obj}")
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    enumeration_errors += 1
                    errors.append(f"Failed to inspect {path_obj}: {exc}")
            if len(records) >= int(max_files):
                limit_reached = True
                break
    else:
        try:
            for entry in os.scandir(str(root)):
                if len(records) >= int(max_files):
                    limit_reached = True
                    break
                try:
                    if entry.is_symlink():
                        skipped_symlinks += 1
                        notes.append(f"Skipped symlink file for safety: {entry.path}")
                        continue
                except OSError:
                    enumeration_errors += 1
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                try:
                    append_record(Path(entry.path), entry.stat(follow_symlinks=False))
                except PermissionError:
                    permission_failures += 1
                    errors.append(f"Permission denied: {entry.path}")
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    enumeration_errors += 1
                    errors.append(f"Failed to inspect {entry.path}: {exc}")
        except PermissionError:
            permission_failures += 1
            errors.append(f"Permission denied: {root}")
        except OSError as exc:
            enumeration_errors += 1
            errors.append(f"Failed to scan {root}: {exc}")
    return records, errors, notes, visited, {
        "permission_failures": permission_failures,
        "skipped_symlinks": skipped_symlinks,
        "enumeration_errors": enumeration_errors,
        "limit_reached": limit_reached,
    }


def _normalize_scan_mode(scan_mode: str) -> str:
    normalized = str(scan_mode or "standard").strip().lower() or "standard"
    if normalized not in {"fast", "standard", "full"}:
        return "standard"
    return normalized


def _is_file_in_scan_scope(path_value: object, *, scan_mode: str) -> bool:
    path = Path(str(path_value or ""))
    suffix = path.suffix.lower()
    normalized_mode = _normalize_scan_mode(scan_mode)
    if normalized_mode == "full":
        return True
    if normalized_mode == "fast":
        return suffix in _FAST_SCAN_SUFFIXES
    return suffix not in _STANDARD_SKIP_SUFFIXES


def _scan_mode_exclusion_message(scan_mode: str, relative_path: str) -> str:
    normalized_mode = _normalize_scan_mode(scan_mode)
    if normalized_mode == "fast":
        return f"Excluded from fast coverage: {relative_path}"
    return f"Excluded from standard coverage: {relative_path}"


def _coverage_scope_description(scan_mode: str) -> str:
    normalized_mode = _normalize_scan_mode(scan_mode)
    if normalized_mode == "fast":
        return "Partial coverage of high-risk file types."
    if normalized_mode == "standard":
        return "Standard coverage excludes low-risk media-style file types."
    return "Full coverage of every eligible regular file."


def _build_incomplete_record(
    item: dict[str, object],
    *,
    scanned_at: str,
    policy: ScanPolicy,
    status: str = "not_scanned",
    scan_health: str = "incomplete",
    message: str,
    backend: str = "",
    scanner: str = "",
    engine_version: str = "",
    database_version: str = "",
    database_date: str = "",
) -> dict[str, object]:
    return {
        **item,
        "malware_status": status,
        "malware_verdict": "not_scanned",
        "malware_scan_health": scan_health,
        "malware_scanner": scanner,
        "malware_backend": backend,
        "malware_engine_version": engine_version,
        "malware_database_version": database_version,
        "malware_database_date": database_date,
        "malware_threat_name": "",
        "malware_message": message,
        "malware_scanned_at": scanned_at,
        "malware_cache_hit": False,
        "malware_policy_name": policy.name,
        "malware_policy_version": policy.policy_version,
        "malware_file_sha256": "",
        "malware_file_size": safe_int(item.get("size_bytes")),
        "malware_file_mtime_ns": safe_int(item.get("mtime_ns")),
        "malware_file_inode": str(item.get("file_inode") or ""),
    }


def _validate_malware_summary(summary: Mapping[str, object]) -> bool:
    total_records = safe_int(summary.get("result_records"))
    reconciled = (
        safe_int(summary.get("clean_files"))
        + safe_int(summary.get("suspicious_files"))
        + safe_int(summary.get("infected_files"))
        + safe_int(summary.get("not_scanned_files"))
    )
    return reconciled == total_records


def scan_folder(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    duplicate_detection: bool = False,
    enable_malware_scan: bool = False,
    malware_scan_timeout_seconds: int = 30,
    malware_database_max_age_days: int = 7,
    progress_callback: Callable[[int, int], None] | None = None,
    malware_scan_policy: str = "standard",
) -> dict[str, object]:
    path_obj = validate_scan_target(folder_path)
    return scan_local_folder(
        str(path_obj),
        recursive=recursive,
        max_files=max_files,
        stale_days=stale_days,
        large_file_bytes=large_file_bytes,
        deep_compare_large_files=duplicate_detection,
        enable_malware_scan=enable_malware_scan,
        malware_scan_timeout_seconds=malware_scan_timeout_seconds,
        malware_database_max_age_days=malware_database_max_age_days,
        malware_scan_policy=malware_scan_policy,
        malware_scan_policy_version="strict-v1" if str(malware_scan_policy).strip().lower() == "strict" else "standard-v1",
        progress_callback=progress_callback,
    )


def scan_folder_malware(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    malware_scan_mode: str = "standard",
    malware_scan_timeout_seconds: int = 30,
    malware_database_max_age_days: int = 7,
    malware_scan_policy: str = "standard",
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    root = validate_scan_target(folder_path)
    started = time.perf_counter()
    policy = _build_folder_scan_policy(
        policy_name=malware_scan_policy,
        timeout_seconds=malware_scan_timeout_seconds,
    )
    scanner = MalwareScanner(
        timeout_seconds=malware_scan_timeout_seconds,
        max_database_age_days=malware_database_max_age_days,
        policy=policy,
    )
    status = scanner.get_status()
    scan_mode = _normalize_scan_mode(malware_scan_mode)
    records, errors, notes, visited, enumeration_stats = _iter_folder_files(
        root,
        recursive=recursive,
        max_files=max_files,
    )
    if status.message:
        notes.append(f"ClamAV: {status.message}")
    scannable_records = [item for item in records if _is_file_in_scan_scope(item.get("path"), scan_mode=scan_mode)]
    path_records = [Path(str(item["path"])) for item in scannable_records]
    results = scanner.scan_paths(
        path_records,
        progress_callback=(
            None
            if progress_callback is None
            else lambda progress: progress_callback(progress.processed, progress.total, progress.stage)
        ),
    )
    metrics = scanner.get_metrics()
    scanned_at = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    enriched_records: list[dict[str, object]] = []
    missing_result_files = 0
    for item in records:
        if not _is_file_in_scan_scope(item.get("path"), scan_mode=scan_mode):
            enriched_records.append(
                _build_incomplete_record(
                    item,
                    scanned_at=scanned_at,
                    policy=policy,
                    message=_scan_mode_exclusion_message(scan_mode, str(item.get("relative_path") or item.get("path") or "")),
                )
            )
            continue
        path_key = str(Path(str(item["path"])).expanduser().resolve(strict=False))
        result = results.get(path_key)
        if result is None:
            missing_result_files += 1
            enriched_records.append(
                _build_incomplete_record(
                    item,
                    scanned_at=scanned_at,
                    policy=policy,
                    message="scanner returned no result",
                )
            )
            continue
        enriched_records.append(
            {
                **item,
                "malware_status": result.status,
                "malware_verdict": result.verdict,
                "malware_scan_health": result.scan_health,
                "malware_scanner": result.scanner,
                "malware_backend": result.backend,
                "malware_engine_version": result.engine_version or "",
                "malware_database_version": result.database_version or "",
                "malware_database_date": result.database_date or "",
                "malware_threat_name": result.threat_name or "",
                "malware_message": result.message,
                "malware_scanned_at": scanned_at,
                "malware_cache_hit": bool(result.cache_hit),
                "malware_policy_name": policy.name,
                "malware_policy_version": policy.policy_version,
                "malware_file_sha256": result.file_sha256 or "",
                "malware_file_size": safe_int(result.file_size or item["size_bytes"]),
                "malware_file_mtime_ns": safe_int(result.file_mtime_ns or item["mtime_ns"]),
                "malware_file_inode": result.file_inode or str(item["file_inode"]),
            }
        )
    elapsed_seconds = round(time.perf_counter() - started, 3)
    total_bytes = sum(int(item.get("size_bytes") or 0) for item in enriched_records)
    clean_count = sum(1 for item in enriched_records if item.get("malware_status") == "clean")
    suspicious_count = sum(1 for item in enriched_records if item.get("malware_status") == "suspicious")
    infected_count = sum(1 for item in enriched_records if item.get("malware_status") == "infected")
    not_scanned_count = sum(1 for item in enriched_records if item.get("malware_status") == "not_scanned")
    scanner_unavailable_count = sum(1 for item in enriched_records if item.get("malware_scan_health") == "scanner_unavailable")
    database_missing_count = sum(1 for item in enriched_records if item.get("malware_scan_health") == "database_missing")
    database_outdated_count = sum(1 for item in enriched_records if item.get("malware_scan_health") == "database_outdated")
    timeout_count = sum(1 for item in enriched_records if item.get("malware_scan_health") == "timeout")
    backend_error_count = sum(1 for item in enriched_records if item.get("malware_scan_health") == "error")
    limit_exceeded_count = sum(1 for item in enriched_records if item.get("malware_scan_health") == "limit_exceeded")
    mode_excluded_count = sum(
        1
        for item in enriched_records
        if "excluded from " in str(item.get("malware_message") or "").strip().lower()
    )
    incomplete_count = sum(
        1
        for item in enriched_records
        if str(item.get("malware_scan_health") or "") != "ok"
    )
    completed_count = len(enriched_records) - incomplete_count
    cache_hits = sum(1 for item in enriched_records if bool(item.get("malware_cache_hit")))
    scan_error_count = sum(
        1
        for item in enriched_records
        if str(item.get("malware_scan_health") or "") in {"scanner_unavailable", "database_missing", "database_outdated", "timeout", "error"}
    )
    result_id = uuid.uuid4().hex
    summary = {
        "scan_mode": scan_mode,
        "coverage_scope": _coverage_scope_description(scan_mode),
        "coverage_is_partial": scan_mode != "full",
        "total_files_considered": len(records),
        "enumerated_files": len(records),
        "result_records": len(enriched_records),
        "files_successfully_scanned": sum(
            1
            for item in enriched_records
            if str(item.get("malware_scan_health") or "") == "ok"
        ),
        "completed_files": completed_count,
        "clean_files": clean_count,
        "suspicious_files": suspicious_count,
        "infected_files": infected_count,
        "not_scanned_files": not_scanned_count,
        "incomplete_files": incomplete_count,
        "incomplete_or_failed_scans": incomplete_count,
        "missing_result_files": missing_result_files,
        "cache_hits": cache_hits,
        "files_sent_to_scanner": int(metrics.files_sent_to_scanner),
        "permission_failures": safe_int(enumeration_stats["permission_failures"]),
        "enumeration_errors": safe_int(enumeration_stats["enumeration_errors"]),
        "skipped_symlinks": safe_int(enumeration_stats["skipped_symlinks"]),
        "scan_errors": scan_error_count,
        "scanner_unavailable_files": scanner_unavailable_count,
        "database_missing_files": database_missing_count,
        "database_outdated_files": database_outdated_count,
        "timeout_files": timeout_count,
        "backend_error_files": backend_error_count,
        "limit_exceeded_files": limit_exceeded_count,
        "mode_excluded_files": mode_excluded_count,
        "limit_reached": bool(enumeration_stats["limit_reached"]),
        "total_bytes": total_bytes,
        "elapsed_seconds": elapsed_seconds,
        "files_per_second": (len(enriched_records) / elapsed_seconds) if elapsed_seconds > 0 else 0.0,
        "bytes_per_second": (total_bytes / elapsed_seconds) if elapsed_seconds > 0 else 0.0,
        "backend": status.selected_backend,
        "engine_version": status.engine_version or "",
        "database_version": status.database_version or "",
        "database_date": status.database_date or "",
        "availability": status.availability,
        "scanner_available": status.selected_backend != "unavailable" and status.availability != "clamscan_missing",
        "database_fresh": status.availability != "database_outdated",
        "enumeration_incomplete": bool(enumeration_stats["permission_failures"] or enumeration_stats["enumeration_errors"]),
    }
    summary["totals_consistent"] = _validate_malware_summary(summary)
    summary["overall_severity"] = malware_result_severity(summary)
    summary["overall_status"] = str(summary["overall_severity"])
    return {
        "result_id": result_id,
        "path": str(root),
        "recursive": bool(recursive),
        "max_files": int(max_files),
        "scan_mode": scan_mode,
        "coverage_scope": _coverage_scope_description(scan_mode),
        "visited_files": visited,
        "policy_name": policy.name,
        "policy_version": policy.policy_version,
        "scanned_at": scanned_at,
        "elapsed_seconds": elapsed_seconds,
        "records": enriched_records,
        "errors": errors[:50],
        "notes": notes[:20],
        "status": {
            "availability": status.availability,
            "selected_backend": status.selected_backend,
            "engine_version": status.engine_version,
            "database_version": status.database_version,
            "database_date": status.database_date,
            "database_age_days": status.database_age_days,
            "message": status.message,
        },
        "summary": summary,
    }


def merge_malware_scan_into_analysis(
    analysis_result: dict[str, object],
    malware_result: dict[str, object] | None,
    *,
    require_malware_scan: bool,
    malware_scan_policy: str,
    malware_database_max_age_days: int,
) -> dict[str, object]:
    merged = dict(analysis_result)
    merged["enable_malware_scan"] = bool(require_malware_scan)
    merged["malware_scan_policy"] = str(malware_scan_policy or "standard")
    merged["malware_scan_policy_version"] = (
        "strict-v1" if str(malware_scan_policy).strip().lower() == "strict" else "standard-v1"
    )
    merged["malware_database_max_age_days"] = int(malware_database_max_age_days)
    malware_records = {
        canonical_path_key(str(item.get("path") or "")): item
        for item in cast(list[dict[str, object]], malware_result.get("records") if isinstance(malware_result, dict) else [])
        if str(item.get("path") or "").strip()
    }
    records = []
    for raw_record in cast(list[dict[str, object]], merged.get("records") or []):
        record = dict(raw_record)
        malware_record = malware_records.get(canonical_path_key(str(record.get("path") or "")))
        if malware_record is None:
            record.update(
                {
                    "malware_status": "not_scanned",
                    "malware_verdict": "not_scanned",
                    "malware_scan_health": "incomplete",
                    "malware_scanner": "",
                    "malware_backend": "",
                    "malware_engine_version": "",
                    "malware_database_version": "",
                    "malware_database_date": "",
                    "malware_threat_name": "",
                    "malware_message": "",
                    "malware_scanned_at": "",
                    "malware_cache_hit": False,
                    "malware_policy_name": "",
                    "malware_policy_version": "",
                    "malware_file_sha256": "",
                    "malware_file_size": 0,
                    "malware_file_mtime_ns": 0,
                    "malware_file_inode": "",
                }
            )
        else:
            for field in (
                "malware_status",
                "malware_verdict",
                "malware_scan_health",
                "malware_scanner",
                "malware_backend",
                "malware_engine_version",
                "malware_database_version",
                "malware_database_date",
                "malware_threat_name",
                "malware_message",
                "malware_scanned_at",
                "malware_cache_hit",
                "malware_policy_name",
                "malware_policy_version",
                "malware_file_sha256",
                "malware_file_size",
                "malware_file_mtime_ns",
                "malware_file_inode",
            ):
                record[field] = malware_record.get(field)
        records.append(record)
    merged["records"] = records
    return merged


def preview_selected_actions(scan_result: dict[str, object], selected_paths: list[str]) -> dict[str, object]:
    return run_folder_organizer(scan_result, selected_paths, dry_run=True)


def build_report_snapshot(scan_result: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(scan_result, dict):
        return None
    return dict(scan_result)


def quarantine_selected_files(
    scan_result: dict[str, object],
    selected_paths: list[str],
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    enable_malware_scan: bool = False,
    malware_scan_timeout_seconds: int = 30,
    malware_database_max_age_days: int = 7,
) -> tuple[dict[str, object], dict[str, object], dict[str, object] | None]:
    report_snapshot = build_report_snapshot(scan_result)
    operation_result = run_folder_organizer(scan_result, selected_paths, dry_run=False)
    refreshed_scan = scan_local_folder(
        str(scan_result.get("path") or ""),
        recursive=recursive,
        max_files=max_files,
        stale_days=stale_days,
        large_file_bytes=large_file_bytes,
        enable_malware_scan=enable_malware_scan,
        malware_scan_timeout_seconds=malware_scan_timeout_seconds,
        malware_database_max_age_days=malware_database_max_age_days,
    )
    return operation_result, refreshed_scan, report_snapshot


def restore_quarantine_selection(
    folder_path: str,
    quarantine_paths: list[str],
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    enable_malware_scan: bool = False,
    malware_scan_timeout_seconds: int = 30,
    malware_database_max_age_days: int = 7,
) -> tuple[dict[str, object], dict[str, object] | None]:
    validated_path = validate_scan_target(folder_path)
    restore_result = restore_quarantined_items(str(validated_path), quarantine_paths)
    refreshed_scan: dict[str, object] | None = None
    try:
        refreshed_scan = scan_local_folder(
            str(validated_path),
            recursive=recursive,
            max_files=max_files,
            stale_days=stale_days,
            large_file_bytes=large_file_bytes,
            enable_malware_scan=enable_malware_scan,
            malware_scan_timeout_seconds=malware_scan_timeout_seconds,
            malware_database_max_age_days=malware_database_max_age_days,
        )
    except FolderOrganizerError:
        refreshed_scan = None
    return restore_result, refreshed_scan


def get_quarantine_items(folder_path: str) -> list[dict[str, object]]:
    return list_quarantine_items(folder_path)


def get_quarantine_items_safe(folder_path: str) -> tuple[list[dict[str, object]], list[str]]:
    return load_quarantine_items_with_warnings(folder_path)


def resolve_report_inputs(
    current_scan: dict[str, object] | None,
    report_snapshot: dict[str, object] | None,
    operation_result: dict[str, object] | None,
) -> tuple[dict[str, object], dict[str, object] | None]:
    export_scan = report_snapshot if isinstance(report_snapshot, dict) else current_scan
    if not isinstance(export_scan, dict):
        export_scan = {}
    export_operation = operation_result if isinstance(operation_result, dict) else None
    return export_scan, export_operation
