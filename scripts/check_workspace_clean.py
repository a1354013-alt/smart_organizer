from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

from scripts.release_policy import (
    SKIP_ROOT_DIRS,
    WORKSPACE_FORBIDDEN_DIR_PATTERNS,
    WORKSPACE_FORBIDDEN_FILE_PATTERNS,
    _matches_any,
    is_allowed_controlled_release_output,
)


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
            if relative_root.parts and _matches_any(relative_root.parts[0], ("release_ci*",)):
                problems.append(candidate)
                continue
            if relative_root == Path(".") and _matches_any(name, ("release_ci*",)):
                kept_dirs.append(name)
                continue
            if is_allowed_controlled_release_output(candidate, project_root=PROJECT_ROOT):
                continue

            if _matches_any(name, WORKSPACE_FORBIDDEN_DIR_PATTERNS):
                problems.append(candidate)
                continue

            kept_dirs.append(name)
        dirs[:] = kept_dirs

        for name in files:
            candidate = root_path / name
            if is_allowed_controlled_release_output(candidate, project_root=PROJECT_ROOT):
                continue
            if relative_root.parts and _matches_any(relative_root.parts[0], ("release_ci*",)):
                problems.append(candidate)
                continue
            if _matches_any(name, WORKSPACE_FORBIDDEN_FILE_PATTERNS):
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
