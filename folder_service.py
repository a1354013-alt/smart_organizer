from __future__ import annotations

import datetime
import os
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import cast

from folder_models import FolderActionResult, FolderOrganizerError, ScanPathError
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
) -> tuple[list[dict[str, object]], list[str], list[str], int]:
    records: list[dict[str, object]] = []
    errors: list[str] = []
    notes: list[str] = []
    visited = 0

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
                        notes.append(f"Skipped symlink directory for safety: {dir_path}")
                        continue
                except OSError:
                    notes.append(f"Skipped unreadable directory entry: {dir_path}")
                    continue
                kept_dirnames.append(name)
            dirnames[:] = kept_dirnames
            for filename in filenames:
                if len(records) >= int(max_files):
                    break
                path_obj = Path(dirpath) / filename
                try:
                    stat_result = path_obj.lstat()
                    if path_obj.is_symlink():
                        notes.append(f"Skipped symlink file for safety: {path_obj}")
                        continue
                    append_record(path_obj, stat_result)
                except PermissionError:
                    errors.append(f"Permission denied: {path_obj}")
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    errors.append(f"Failed to inspect {path_obj}: {exc}")
            if len(records) >= int(max_files):
                break
    else:
        try:
            for entry in os.scandir(str(root)):
                if len(records) >= int(max_files):
                    break
                try:
                    if entry.is_symlink():
                        notes.append(f"Skipped symlink file for safety: {entry.path}")
                        continue
                except OSError:
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
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
    return records, errors, notes, visited


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
    records, errors, notes, visited = _iter_folder_files(
        root,
        recursive=recursive,
        max_files=max_files,
    )
    if status.message:
        notes.append(f"ClamAV: {status.message}")
    path_records = [Path(str(item["path"])) for item in records]
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
    for item in records:
        path_key = str(Path(str(item["path"])).expanduser().resolve(strict=False))
        result = results.get(path_key)
        if result is None:
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
                "malware_file_size": int(result.file_size or item["size_bytes"]),
                "malware_file_mtime_ns": int(result.file_mtime_ns or item["mtime_ns"]),
                "malware_file_inode": result.file_inode or str(item["file_inode"]),
            }
        )
    elapsed_seconds = round(time.perf_counter() - started, 3)
    total_bytes = sum(int(item.get("size_bytes") or 0) for item in enriched_records)
    clean_count = sum(1 for item in enriched_records if item.get("malware_status") == "clean")
    suspicious_count = sum(1 for item in enriched_records if item.get("malware_status") == "suspicious")
    infected_count = sum(1 for item in enriched_records if item.get("malware_status") == "infected")
    incomplete_count = sum(
        1
        for item in enriched_records
        if str(item.get("malware_scan_health") or "") != "ok" or str(item.get("malware_status") or "") not in {"clean", "suspicious", "infected"}
    )
    result_id = uuid.uuid4().hex
    return {
        "result_id": result_id,
        "path": str(root),
        "recursive": bool(recursive),
        "max_files": int(max_files),
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
        "summary": {
            "total_files_considered": len(enriched_records),
            "files_successfully_scanned": sum(
                1 for item in enriched_records if str(item.get("malware_scan_health") or "") == "ok"
            ),
            "clean_files": clean_count,
            "suspicious_files": suspicious_count,
            "infected_files": infected_count,
            "incomplete_or_failed_scans": incomplete_count,
            "cache_hits": int(metrics.cache_hits),
            "files_sent_to_scanner": int(metrics.files_sent_to_scanner),
            "total_bytes": total_bytes,
            "elapsed_seconds": elapsed_seconds,
            "files_per_second": (len(enriched_records) / elapsed_seconds) if elapsed_seconds > 0 else 0.0,
            "bytes_per_second": (total_bytes / elapsed_seconds) if elapsed_seconds > 0 else 0.0,
            "backend": status.selected_backend,
            "engine_version": status.engine_version or "",
            "database_version": status.database_version or "",
            "database_date": status.database_date or "",
        },
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
