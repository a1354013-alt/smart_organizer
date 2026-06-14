from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

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


def scan_folder(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int,
    enable_malware_scan: bool = False,
    malware_scan_timeout_seconds: int = 30,
    malware_database_max_age_days: int = 7,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    path_obj = validate_scan_target(folder_path)
    return scan_local_folder(
        str(path_obj),
        recursive=recursive,
        max_files=max_files,
        stale_days=stale_days,
        large_file_bytes=large_file_bytes,
        enable_malware_scan=enable_malware_scan,
        malware_scan_timeout_seconds=malware_scan_timeout_seconds,
        malware_database_max_age_days=malware_database_max_age_days,
        progress_callback=progress_callback,
    )


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
