from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

from scripts.release_policy import SKIP_ROOT_DIRS

FORBIDDEN_CACHE_DIR_PATTERNS: tuple[str, ...] = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".compileall_cache",
    ".pytest_runtime_tmp*",
    "htmlcov",
)
FORBIDDEN_CACHE_FILE_PATTERNS: tuple[str, ...] = (
    "*.pyc",
    "*.pyo",
    ".coverage",
    ".coverage.*",
    "coverage.xml",
)


def _sorted_matches(pattern: str, *, root: Path) -> list[Path]:
    return sorted(path for path in root.rglob(pattern) if path.exists())


def cleanup_workspace(project_root: Path = PROJECT_ROOT) -> list[Path]:
    removed: list[Path] = []

    for pattern in FORBIDDEN_CACHE_DIR_PATTERNS:
        for path in _sorted_matches(pattern, root=project_root):
            try:
                relative = path.relative_to(project_root)
            except ValueError:
                continue
            if relative.parts and relative.parts[0] in SKIP_ROOT_DIRS:
                continue
            if not path.is_dir():
                continue
            shutil.rmtree(path, ignore_errors=True)
            if not path.exists():
                removed.append(path)

    for pattern in FORBIDDEN_CACHE_FILE_PATTERNS:
        for path in _sorted_matches(pattern, root=project_root):
            try:
                relative = path.relative_to(project_root)
            except ValueError:
                continue
            if relative.parts and relative.parts[0] in SKIP_ROOT_DIRS:
                continue
            if not path.is_file():
                continue
            path.unlink(missing_ok=True)
            if not path.exists():
                removed.append(path)

    return sorted(set(removed))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove generated development artifacts from the workspace.")
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Project root to clean. Defaults to the current repository root.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    project_root = Path(args.project_root).resolve()
    removed = cleanup_workspace(project_root)
    if removed:
        print("Removed workspace artifacts:")
        for path in removed:
            print(f"- {path.relative_to(project_root).as_posix()}")
    else:
        print("No workspace artifacts to remove.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
