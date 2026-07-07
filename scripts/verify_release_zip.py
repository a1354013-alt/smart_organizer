from __future__ import annotations

import argparse
import glob
import sys
from pathlib import Path
from zipfile import ZipFile

sys.dont_write_bytecode = True

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.conflict_markers import find_conflict_markers_in_zip
from scripts.create_release_zip import RELEASE_ALLOWLIST, zip_contains_forbidden_entries
from scripts.release_policy import (
    DEFAULT_RELEASE_OUTPUT_DIR,
    SOURCE_ONLY_RELEASE_FILES,
    normalize_relative_path,
)


def verify_release_zip(zip_path: Path) -> None:
    if not zip_path.exists():
        raise FileNotFoundError(f"Release zip not found: {zip_path}")
    forbidden = zip_contains_forbidden_entries(zip_path)
    if forbidden:
        raise ValueError(f"Release zip contains forbidden paths: {forbidden}")
    with ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        python_sources = {
            name: archive.read(name).decode("utf-8")
            for name in names
            if name.endswith(".py")
        }

    expected = {path.replace("\\", "/") for path in RELEASE_ALLOWLIST}
    missing = sorted(expected - names)
    extra = sorted(names - expected)
    source_only_hits = sorted(
        name for name in names if normalize_relative_path(name) in SOURCE_ONLY_RELEASE_FILES
    )
    if missing:
        raise ValueError(f"Release zip is missing allowlisted files: {missing}")
    if extra:
        raise ValueError(f"Release zip contains non-allowlisted files: {extra}")
    if source_only_hits:
        raise ValueError(f"Release zip contains source-only files: {source_only_hits}")
    conflict_hits = find_conflict_markers_in_zip(zip_path)
    if conflict_hits:
        raise ValueError(f"Release zip contains conflict markers: {conflict_hits}")
    syntax_errors: list[str] = []
    for name, source in python_sources.items():
        try:
            compile(source, name, "exec", dont_inherit=True, optimize=0)
        except SyntaxError as exc:
            syntax_errors.append(f"{name}: {exc.msg} (line {exc.lineno})")
    if syntax_errors:
        raise ValueError(f"Release zip contains invalid Python files: {syntax_errors}")


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


def default_zip_path_arg() -> str:
    candidates: list[Path] = []
    for pattern in (f"{DEFAULT_RELEASE_OUTPUT_DIR}/*.zip",):
        candidates.extend(Path(value) for value in glob.glob(str(PROJECT_ROOT / pattern)))
    if not candidates:
        raise FileNotFoundError(f"No release zip found in {DEFAULT_RELEASE_OUTPUT_DIR}/.")
    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    return str(latest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify Smart Organizer release zip policy.")
    parser.add_argument("zip_path", nargs="?", default="", help="Path to release zip.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    zip_path_arg = str(args.zip_path or "").strip() or default_zip_path_arg()
    matched_paths = resolve_zip_paths(zip_path_arg)
    for zip_path in matched_paths:
        verify_release_zip(zip_path)
        print(f"Release zip verified: {zip_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
