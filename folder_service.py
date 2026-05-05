from __future__ import annotations

from pathlib import Path
from typing import Callable

from folder_models import FolderOrganizerError, ScanPathError
from folder_organizer import (
    list_quarantine_items,
    restore_quarantined_items,
    run_folder_organizer,
    scan_local_folder,
)


def validate_scan_target(folder_path: str) -> Path:
    normalized = str(folder_path or "").strip().strip('"')
    if not normalized:
        raise ScanPathError("Enter a folder path first.")

    path_obj = Path(normalized).expanduser()
    if not path_obj.exists():
        raise ScanPathError("The folder does not exist.")
    if not path_obj.is_dir():
        raise ScanPathError("The path must point to a folder.")
    return path_obj


def scan_folder(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    path_obj = validate_scan_target(folder_path)
    return scan_local_folder(
        str(path_obj),
        recursive=recursive,
        max_files=max_files,
        stale_days=stale_days,
        large_file_bytes=large_file_bytes,
        progress_callback=progress_callback,
    )


def preview_selected_actions(scan_result: dict[str, object], selected_paths: list[str]) -> dict[str, object]:
    return run_folder_organizer(scan_result, selected_paths, dry_run=True)


def quarantine_selected_files(
    scan_result: dict[str, object],
    selected_paths: list[str],
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
) -> tuple[dict[str, object], dict[str, object]]:
    operation_result = run_folder_organizer(scan_result, selected_paths, dry_run=False)
    refreshed_scan = scan_local_folder(
        str(scan_result.get("path") or ""),
        recursive=recursive,
        max_files=max_files,
        stale_days=stale_days,
        large_file_bytes=large_file_bytes,
    )
    return operation_result, refreshed_scan


def restore_quarantine_selection(
    folder_path: str,
    quarantine_paths: list[str],
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
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
        )
    except FolderOrganizerError:
        refreshed_scan = None
    return restore_result, refreshed_scan


def get_quarantine_items(folder_path: str) -> list[dict[str, object]]:
    return list_quarantine_items(folder_path)
