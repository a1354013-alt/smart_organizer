from __future__ import annotations

import argparse
import fnmatch
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_DIR_PATTERNS = (
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".compileall_cache",
    "uploads",
    "repo",
    "release",
    "dist",
    "build",
    ".pytest_runtime_tmp*",
)

FORBIDDEN_FILE_PATTERNS = (
    "*.pyc",
    "*.pyc.*",
    "*.pyo",
    "*.pyd",
    "*.db",
    "*.sqlite",
    "*.sqlite3",
)

ALLOWED_RELEASE_OUTPUT_PATTERNS = ("*.zip",)

SKIP_ROOT_DIRS = {".git", ".github", ".venv", "venv", "node_modules"}


def _matches_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)


def _is_allowed_release_output(path: Path) -> bool:
    parts = path.relative_to(PROJECT_ROOT).parts
    if not parts:
        return False
    root_name = parts[0]
    if not fnmatch.fnmatch(root_name, "release_ci*"):
        return False
    if path.is_dir():
        return len(parts) == 1
    return _matches_any(path.name, ALLOWED_RELEASE_OUTPUT_PATTERNS)


def find_workspace_pollution() -> list[Path]:
    problems: list[Path] = []

    for root, dirs, files in os.walk(PROJECT_ROOT):
        root_path = Path(root)
        relative_root = root_path.relative_to(PROJECT_ROOT)

        kept_dirs: list[str] = []
        for name in dirs:
            if relative_root == Path(".") and name in SKIP_ROOT_DIRS:
                continue

            candidate = root_path / name
            if relative_root.parts and fnmatch.fnmatch(relative_root.parts[0], "release_ci*"):
                problems.append(candidate)
                continue
            if relative_root == Path(".") and fnmatch.fnmatch(name, "release_ci*"):
                kept_dirs.append(name)
                continue
            if _is_allowed_release_output(candidate):
                continue

            if _matches_any(name, FORBIDDEN_DIR_PATTERNS):
                problems.append(candidate)
                continue

            kept_dirs.append(name)
        dirs[:] = kept_dirs

        for name in files:
            candidate = root_path / name
            if _is_allowed_release_output(candidate):
                continue
            if relative_root.parts and fnmatch.fnmatch(relative_root.parts[0], "release_ci*"):
                problems.append(candidate)
                continue
            if _matches_any(name, FORBIDDEN_FILE_PATTERNS):
                problems.append(candidate)

    return sorted(set(problems))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check the workspace for delivery pollution.")
    parser.add_argument(
        "--project-root",
        default=str(PROJECT_ROOT),
        help="Project root to scan. Defaults to the current repository root.",
    )
    return parser.parse_args()


def main() -> int:
    global PROJECT_ROOT

    args = parse_args()
    project_root = Path(args.project_root).resolve()
    PROJECT_ROOT = project_root

    pollution = find_workspace_pollution()
    if pollution:
        lines = "\n".join(f"- {path.relative_to(PROJECT_ROOT).as_posix()}" for path in pollution)
        raise SystemExit(f"Workspace is not clean for delivery:\n{lines}")

    print(f"Workspace is clean: {PROJECT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
