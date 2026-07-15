from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True


def cleanup_validation_artifacts(project_root: Path = PROJECT_ROOT) -> list[Path]:
    removed: list[Path] = []
    for relative in (".coverage", "coverage.xml"):
        path = project_root / relative
        if path.exists() and path.is_file():
            path.unlink()
            removed.append(path)
    return removed


def main() -> int:
    removed = cleanup_validation_artifacts()
    if removed:
        print("Removed validation artifacts:")
        for path in removed:
            print(f"- {path.relative_to(PROJECT_ROOT).as_posix()}")
    else:
        print("No validation artifacts to remove.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
