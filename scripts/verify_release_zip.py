from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.create_release_zip import RELEASE_ALLOWLIST, zip_contains_forbidden_entries


def verify_release_zip(zip_path: Path) -> None:
    if not zip_path.exists():
        raise FileNotFoundError(f"Release zip not found: {zip_path}")
    forbidden = zip_contains_forbidden_entries(zip_path)
    if forbidden:
        raise ValueError(f"Release zip contains forbidden paths: {forbidden}")

    import zipfile

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    expected = {path.replace("\\", "/") for path in RELEASE_ALLOWLIST}
    missing = sorted(expected - names)
    extra = sorted(names - expected)
    if missing:
        raise ValueError(f"Release zip is missing allowlisted files: {missing}")
    if extra:
        raise ValueError(f"Release zip contains non-allowlisted files: {extra}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Smart Organizer release zip policy.")
    parser.add_argument("zip_path", help="Path to release zip.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    verify_release_zip(Path(args.zip_path))
    print(f"Release zip verified: {Path(args.zip_path).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
