from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

from runtime_preflight import require_supported_python
from scripts.release_policy import (
    DEFAULT_RELEASE_OUTPUT_DIR,
    FORBIDDEN_RELEASE_PATTERNS,
    RUNTIME_RELEASE_ALLOWLIST,
    RUNTIME_RELEASE_ALLOWLIST_GROUPS,
    release_forbidden_entries,
)

RELEASE_ALLOWLIST_GROUPS = {
    group: list(paths)
    for group, paths in RUNTIME_RELEASE_ALLOWLIST_GROUPS.items()
}
RELEASE_ALLOWLIST = list(RUNTIME_RELEASE_ALLOWLIST)
FORBIDDEN_PATTERNS = list(FORBIDDEN_RELEASE_PATTERNS)

STAGING_CLEANUP_RETRIES = 20
STAGING_CLEANUP_DELAY_SECONDS = 0.1


def get_version() -> str:
    version_path = PROJECT_ROOT / "version.py"
    source = version_path.read_text(encoding="utf-8")
    match = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']\s*$", source, flags=re.MULTILINE)
    if not match:
        raise RuntimeError(f"Could not parse __version__ from {version_path}")
    return match.group(1)


def _remove_tree_with_retries(path: Path) -> None:
    if not path.exists():
        return
    last_error: OSError | None = None
    for attempt in range(STAGING_CLEANUP_RETRIES):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except OSError as exc:
            last_error = exc
            if attempt + 1 >= STAGING_CLEANUP_RETRIES:
                break
            time.sleep(STAGING_CLEANUP_DELAY_SECONDS)
    raise OSError(f"Failed to remove staging directory {path}: {last_error}") from last_error


def build_zip(output_dir: Path, zip_name: str | None = None) -> Path:
    version = get_version()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    output_dir.mkdir(parents=True, exist_ok=True)

    if not zip_name:
        zip_name = f"{PROJECT_ROOT.name}-v{version}-runtime-demo-{timestamp}.zip"

    zip_path = output_dir / zip_name
    staging_dir = output_dir / f"_staging_{timestamp}"

    if staging_dir.exists():
        _remove_tree_with_retries(staging_dir)

    staging_dir.mkdir(parents=True)

    try:
        for relative in RELEASE_ALLOWLIST:
            source = PROJECT_ROOT / relative

            if not source.exists():
                raise FileNotFoundError(f"Release allowlist item is missing: {relative}")

            if source.is_dir():
                raise IsADirectoryError(
                    f"Release allowlist must not include directories: {relative}"
                )

            destination = staging_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        if zip_path.exists():
            zip_path.unlink()

        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative in RELEASE_ALLOWLIST:
                archive.write(
                    staging_dir / relative,
                    arcname=relative.replace(os.sep, "/"),
                )
    finally:
        _remove_tree_with_retries(staging_dir)

    return zip_path


def zip_contains_forbidden_entries(zip_path: Path) -> list[str]:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    return release_forbidden_entries(names)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the official Smart Organizer runtime/demo release zip."
    )

    parser.add_argument(
        "--output-dir",
        default=DEFAULT_RELEASE_OUTPUT_DIR,
        help="Directory where the release zip will be written.",
    )
    parser.add_argument(
        "--zip-name",
        default="",
        help="Optional explicit zip file name.",
    )

    return parser.parse_args()


def main() -> int:
    require_supported_python()
    args = parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = PROJECT_ROOT / output_dir

    zip_path = build_zip(output_dir, args.zip_name or None)
    forbidden = zip_contains_forbidden_entries(zip_path)

    if forbidden:
        raise SystemExit(f"Release zip contains forbidden paths: {forbidden}")

    print(f"Release zip created: {zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
