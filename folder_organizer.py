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
    FolderActionResult,
    FolderOperationResult,
    FolderOperationRow,
    FolderOperationSummary,
    FolderScanRecord,
    FolderScanResult,
    FolderScanStats,
    dict_object,
    human_bytes,
    infer_local_file_kind,
    is_relative_to_path,
    iso_now,
    load_manifest,
    object_list,
    quarantine_dir,
    safe_destination,
    safe_int,
    save_manifest,
    string_list,
)


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
        shutil.move(str(source), str(target))
        return FolderActionResult(success=True, source=str(source), target=str(target))


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
    records: list[FolderScanRecord] = []
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
                recommendation=_recommendation(reasons),
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
    root = Path(str(scan_result.get("path") or "")).expanduser()
    records = {
        str(dict_object(item).get("path")): dict_object(item)
        for item in object_list(scan_result.get("records"))
    }
    operation_id = uuid.uuid4().hex
    results: list[FolderOperationRow] = []
    manifest = load_manifest(root)
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
                    file_size=0,
                    last_modified=None,
                    processed_at=iso_now(),
                    error_message="Selected file is not available in the current scan result.",
                    operation_id=operation_id,
                )
            )
            continue

        original_path = Path(selected_path)
        reasons = ", ".join(string_list(record.get("candidate_reasons"))) or "Selected manually"
        file_size = safe_int(record.get("size_bytes"))
        last_modified = record.get("mtime")
        if dry_run:
            results.append(
                FolderOperationRow(
                    original_path=str(original_path),
                    new_path=str(quarantine_dir(root) / operation_id / original_path.name),
                    status="SKIPPED",
                    reason=reasons,
                    file_size=file_size,
                    last_modified=str(last_modified) if last_modified is not None else None,
                    processed_at=iso_now(),
                    error_message="Dry-run preview only.",
                    operation_id=operation_id,
                )
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
                FolderOperationRow(
                    original_path=str(original_path),
                    new_path=str(destination),
                    status="SUCCESS",
                    reason=reasons,
                    file_size=file_size,
                    last_modified=str(last_modified) if last_modified is not None else None,
                    processed_at=iso_now(),
                    error_message=None,
                    operation_id=operation_id,
                )
            )
        except Exception as exc:
            results.append(
                FolderOperationRow(
                    original_path=str(original_path),
                    new_path=None,
                    status="FAILED",
                    reason=reasons,
                    file_size=file_size,
                    last_modified=str(last_modified) if last_modified is not None else None,
                    processed_at=iso_now(),
                    error_message=str(exc) or type(exc).__name__,
                    operation_id=operation_id,
                )
            )

    if not dry_run:
        manifest["items"] = manifest_items
        save_manifest(root, manifest)

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
            if not source.exists():
                raise FileNotFoundError("Quarantined file is missing.")
            destination = safe_destination(original)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            item["status"] = "RESTORED"
            item["restored_at"] = iso_now()
            item["restored_path"] = str(destination)
            results.append(
                FolderOperationRow(
                    original_path=str(original),
                    new_path=str(destination),
                    status="SUCCESS",
                    reason=str(item.get("reason") or ""),
                    file_size=safe_int(item.get("file_size")),
                    last_modified=str(item.get("last_modified") or "") or None,
                    processed_at=iso_now(),
                    error_message=None,
                    operation_id=str(item.get("operation_id") or "") or None,
                )
            )
        except Exception as exc:
            results.append(
                FolderOperationRow(
                    original_path=str(original) if item.get("original_path") else None,
                    new_path=None,
                    status="FAILED",
                    reason=str(item.get("reason") or ""),
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
