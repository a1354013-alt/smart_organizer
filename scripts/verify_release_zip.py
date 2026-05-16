from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path

sys.dont_write_bytecode = True

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


def resolve_zip_paths(zip_path_arg: str) -> list[Path]:
    pattern = str(zip_path_arg or "").strip()
    if not pattern:
        raise FileNotFoundError("Release zip path is required.")

    has_glob = any(token in pattern for token in "*?[")
    if not has_glob:
        return [Path(pattern)]

    matches = sorted(Path(value) for value in glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"Release zip not found: {pattern}")
    return matches


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Smart Organizer release zip policy.")
    parser.add_argument("zip_path", help="Path to release zip.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matched_paths = resolve_zip_paths(args.zip_path)
    for zip_path in matched_paths:
        verify_release_zip(zip_path)
        print(f"Release zip verified: {zip_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
