from __future__ import annotations

from pathlib import Path
from typing import Iterable

from folder_models import FolderActionResult
from folder_organizer import FolderOrganizer


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
