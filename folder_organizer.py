from __future__ import annotations

import shutil
from pathlib import Path

from folder_models import FolderActionResult, is_relative_to_path


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
