from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def is_relative_to_path(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


@dataclass(slots=True)
class FolderActionResult:
    success: bool
    source: str
    target: str | None = None
    error: str | None = None
