from __future__ import annotations

import datetime
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable

from folder_models import (
    QUARANTINE_DIRNAME,
    dict_object,
    human_bytes,
    infer_local_file_kind,
    iso_now,
    load_manifest,
    object_list,
    quarantine_dir,
    safe_destination,
    safe_int,
    save_manifest,
    string_list,
)


def _candidate_reasons(size_bytes: int, stale_days_since_touch: int | None, large_file_bytes: int) -> list[str]:
    reasons: list[str] = []
    if stale_days_since_touch is not None and stale_days_since_touch >= 0:
        reasons.append(f"Unused for {stale_days_since_touch} days")
    if size_bytes >= large_file_bytes:
        reasons.append(f"Large file ({human_bytes(size_bytes)})")
    return reasons


def _recommendation(reasons: list[str]) -> str:
    if not reasons:
        return "Not recommended for automatic handling"
    if len(reasons) >= 2:
        return "Safe to archive"
    if reasons[0].startswith("Unused"):
        return "Safe to archive"
    return "Needs manual review"


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
    root = Path(folder_path).expanduser()
    records: list[dict[str, object]] = []
    errors: list[str] = []
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_delta = datetime.timedelta(days=max(0, int(stale_days)))
    scanned = 0
    visited = 0

    def append_record(path_obj: Path, stat_result: os.stat_result) -> None:
        nonlocal scanned
        mtime = datetime.datetime.fromtimestamp(stat_result.st_mtime, tz=datetime.timezone.utc)
        atime = datetime.datetime.fromtimestamp(stat_result.st_atime, tz=datetime.timezone.utc)
        age_days = int((now - max(mtime, atime)).days)
        stale_age_days = (
            age_days
            if stale_days == 0 or (stale_days > 0 and (now - max(mtime, atime)) >= stale_delta)
            else None
        )
        reasons = _candidate_reasons(int(stat_result.st_size), stale_age_days, int(large_file_bytes))
        records.append(
            {
                "path": str(path_obj),
                "name": path_obj.name,
                "ext": path_obj.suffix.lower(),
                "size_bytes": int(stat_result.st_size),
                "mtime": mtime.isoformat(),
                "atime": atime.isoformat(),
                "days_since_access": age_days,
                "file_kind": infer_local_file_kind(str(path_obj)),
                "is_stale": stale_age_days is not None,
                "is_large": int(stat_result.st_size) >= int(large_file_bytes),
                "candidate_reasons": reasons,
                "recommendation": _recommendation(reasons),
            }
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
                except Exception as exc:
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
                except Exception as exc:
                    errors.append(f"Failed to inspect {entry.path}: {exc}")
        except PermissionError:
            errors.append(f"Permission denied: {root}")

    quarantine_items = list_quarantine_items(str(root))
    stats = {
        "scanned_files": scanned,
        "visited_files": visited,
        "total_bytes": sum(safe_int(item.get("size_bytes")) for item in records),
        "stale_candidates": sum(1 for item in records if item.get("is_stale")),
        "large_candidates": sum(1 for item in records if item.get("is_large")),
        "quarantine_files": len(quarantine_items),
    }
    return {
        "path": str(root),
        "recursive": bool(recursive),
        "max_files": int(max_files),
        "stale_days": int(stale_days),
        "large_file_bytes": int(large_file_bytes),
        "scanned_at": iso_now(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "records": records,
        "errors": errors[:50],
        "stats": stats,
    }


def run_folder_organizer(
    scan_result: dict[str, object],
    selected_paths: list[str],
    *,
    dry_run: bool,
) -> dict[str, object]:
    root = Path(str(scan_result.get("path") or "")).expanduser()
    records = {
        str(dict_object(item).get("path")): dict_object(item)
        for item in object_list(scan_result.get("records"))
    }
    operation_id = uuid.uuid4().hex
    results: list[dict[str, object]] = []
    manifest = load_manifest(root)
    manifest_items = [dict_object(item) for item in object_list(manifest.get("items"))]

    for selected_path in selected_paths:
        record = records.get(selected_path)
        if not record:
            results.append(
                {
                    "original_path": selected_path,
                    "new_path": None,
                    "status": "FAILED",
                    "reason": "Not found in current scan result",
                    "file_size": 0,
                    "last_modified": None,
                    "processed_at": iso_now(),
                    "error_message": "Selected file is not available in the current scan result.",
                    "operation_id": operation_id,
                }
            )
            continue

        original_path = Path(selected_path)
        reasons = ", ".join(string_list(record.get("candidate_reasons"))) or "Selected manually"
        file_size = safe_int(record.get("size_bytes"))
        last_modified = record.get("mtime")
        if dry_run:
            results.append(
                {
                    "original_path": str(original_path),
                    "new_path": str(quarantine_dir(root) / operation_id / original_path.name),
                    "status": "SKIPPED",
                    "reason": reasons,
                    "file_size": file_size,
                    "last_modified": last_modified,
                    "processed_at": iso_now(),
                    "error_message": "Dry-run preview only.",
                    "operation_id": operation_id,
                }
            )
            continue

        try:
            if not original_path.exists():
                raise FileNotFoundError("Source file no longer exists.")
            try:
                relative_path = original_path.relative_to(root)
            except ValueError:
                relative_path = Path(original_path.name)
            destination = quarantine_dir(root) / operation_id / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination = safe_destination(destination)
            shutil.move(str(original_path), str(destination))
            manifest_items.append(
                {
                    "original_path": str(original_path),
                    "quarantine_path": str(destination),
                    "moved_at": iso_now(),
                    "file_size": file_size,
                    "reason": reasons,
                    "operation_id": operation_id,
                    "last_modified": last_modified,
                    "status": "ACTIVE",
                }
            )
            results.append(
                {
                    "original_path": str(original_path),
                    "new_path": str(destination),
                    "status": "SUCCESS",
                    "reason": reasons,
                    "file_size": file_size,
                    "last_modified": last_modified,
                    "processed_at": iso_now(),
                    "error_message": None,
                    "operation_id": operation_id,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "original_path": str(original_path),
                    "new_path": None,
                    "status": "FAILED",
                    "reason": reasons,
                    "file_size": file_size,
                    "last_modified": last_modified,
                    "processed_at": iso_now(),
                    "error_message": str(exc) or type(exc).__name__,
                    "operation_id": operation_id,
                }
            )

    if not dry_run:
        manifest["items"] = manifest_items
        save_manifest(root, manifest)

    return {
        "operation_id": operation_id,
        "dry_run": dry_run,
        "results": results,
        "summary": {
            "selected": len(selected_paths),
            "success": sum(1 for item in results if item["status"] == "SUCCESS"),
            "failed": sum(1 for item in results if item["status"] == "FAILED"),
            "skipped": sum(1 for item in results if item["status"] == "SKIPPED"),
        },
    }


def list_quarantine_items(folder_path: str) -> list[dict[str, object]]:
    root = Path(folder_path).expanduser()
    manifest = load_manifest(root)
    items = []
    for item in object_list(manifest.get("items")):
        item_dict = dict_object(item)
        if str(item_dict.get("status") or "ACTIVE") == "ACTIVE":
            items.append(item_dict)
    return items


def restore_quarantined_items(folder_path: str, quarantine_paths: list[str]) -> dict[str, object]:
    root = Path(folder_path).expanduser()
    manifest = load_manifest(root)
    items = [dict_object(item) for item in object_list(manifest.get("items"))]
    lookup = {str(item.get("quarantine_path")): item for item in items}
    results: list[dict[str, object]] = []

    for quarantine_path in quarantine_paths:
        item = lookup.get(quarantine_path)
        if item is None:
            results.append(
                {
                    "original_path": None,
                    "new_path": None,
                    "status": "FAILED",
                    "reason": "Manifest entry not found",
                    "file_size": 0,
                    "last_modified": None,
                    "processed_at": iso_now(),
                    "error_message": "Manifest entry not found.",
                    "operation_id": None,
                }
            )
            continue
        source = Path(str(item.get("quarantine_path") or ""))
        original = Path(str(item.get("original_path") or ""))
        try:
            if not source.exists():
                raise FileNotFoundError("Quarantined file is missing.")
            destination = safe_destination(original)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            item["status"] = "RESTORED"
            item["restored_at"] = iso_now()
            item["restored_path"] = str(destination)
            results.append(
                {
                    "original_path": str(original),
                    "new_path": str(destination),
                    "status": "SUCCESS",
                    "reason": item.get("reason"),
                    "file_size": safe_int(item.get("file_size")),
                    "last_modified": item.get("last_modified"),
                    "processed_at": iso_now(),
                    "error_message": None,
                    "operation_id": item.get("operation_id"),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "original_path": str(original) if item.get("original_path") else None,
                    "new_path": None,
                    "status": "FAILED",
                    "reason": item.get("reason"),
                    "file_size": safe_int(item.get("file_size")),
                    "last_modified": item.get("last_modified"),
                    "processed_at": iso_now(),
                    "error_message": str(exc) or type(exc).__name__,
                    "operation_id": item.get("operation_id"),
                }
            )

    manifest["items"] = items
    save_manifest(root, manifest)
    return {
        "results": results,
        "summary": {
            "selected": len(quarantine_paths),
            "success": sum(1 for item in results if item["status"] == "SUCCESS"),
            "failed": sum(1 for item in results if item["status"] == "FAILED"),
            "skipped": 0,
        },
    }
