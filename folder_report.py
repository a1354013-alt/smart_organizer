from __future__ import annotations

from typing import Iterable

from folder_models import FolderActionResult


def summarize_folder_actions(actions: Iterable[FolderActionResult]) -> dict[str, int]:
    total = 0
    success = 0
    failed = 0

    for action in actions:
        total += 1
        if action.success:
            success += 1
        else:
            failed += 1

    return {
        "total": total,
        "success": success,
        "failed": failed,
    }
