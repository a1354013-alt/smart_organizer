from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.safe_compileall import main


def _snapshot_pycache_dirs(root: Path) -> set[Path]:
    return {path.resolve() for path in root.rglob("__pycache__")}


def _cleanup_new_pycache_dirs(root: Path, before: set[Path]) -> None:
    for path in sorted(_snapshot_pycache_dirs(root) - before, reverse=True):
        if not path.is_dir():
            continue
        for child in path.iterdir():
            if child.is_file():
                child.unlink(missing_ok=True)
        path.rmdir()


def _restore_missing_pycache_dirs(before: set[Path]) -> None:
    for path in sorted(before):
        path.mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    has_target = any(not token.startswith("-") for token in sys.argv[1:])
    if not has_target:
        sys.argv.append(str(PROJECT_ROOT))
    pycache_before = _snapshot_pycache_dirs(PROJECT_ROOT)
    try:
        main()
    finally:
        _cleanup_new_pycache_dirs(PROJECT_ROOT, pycache_before)
        _restore_missing_pycache_dirs(pycache_before)
