from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from folder_models import FolderActionResult, FolderOrganizerError, ScanPathError
from folder_organizer import (
    FolderOrganizer,
    list_quarantine_items,
    restore_quarantined_items,
    run_folder_organizer,
    scan_local_folder,
)


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


def build_report_snapshot(scan_result: dict[str, object] | None) -> dict[str, object] | None:
    if not isinstance(scan_result, dict):
        return None
    return {key: value for key, value in scan_result.items()}


def quarantine_selected_files(
    scan_result: dict[str, object],
    selected_paths: list[str],
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
) -> tuple[dict[str, object], dict[str, object], dict[str, object] | None]:
    report_snapshot = build_report_snapshot(scan_result)
    operation_result = run_folder_organizer(scan_result, selected_paths, dry_run=False)
    refreshed_scan = scan_local_folder(
        str(scan_result.get("path") or ""),
        recursive=recursive,
        max_files=max_files,
        stale_days=stale_days,
        large_file_bytes=large_file_bytes,
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
