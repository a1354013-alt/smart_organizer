from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.dont_write_bytecode = True


DEMO_FILES: tuple[tuple[str, bytes, int], ...] = (
    ("old_invoice_2022.txt", b"Invoice 2022\nVendor: Demo Co.\nAmount: 1280\n", 760),
    ("old_large_video.mp4.fake", b"fake video placeholder\n" * 128, 900),
    ("screenshot_2021.png.fake", b"fake screenshot placeholder\n", 1100),
    ("recent_notes.txt", b"Recent meeting notes. Keep handy.\n", 3),
    ("duplicate_a.txt", b"duplicate content demo\n", 500),
    ("duplicate_b.txt", b"duplicate content demo\n", 500),
    ("readme_keep.txt", b"Keep this file to show the do-not-touch risk label.\n", 120),
)


@dataclass(frozen=True)
class DemoFolderResult:
    target: Path
    dry_run: bool
    created: tuple[Path, ...]
    preserved_existing: tuple[Path, ...]


def create_demo_folder(
    target: Path,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> DemoFolderResult:
    now = now or datetime.now()
    created: list[Path] = []
    preserved_existing: list[Path] = []
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
    for name, payload, age_days in DEMO_FILES:
        path = target / name
        if path.exists():
            preserved_existing.append(path)
            continue
        timestamp = (now - timedelta(days=age_days)).timestamp()
        created.append(path)
        if dry_run:
            continue
        path.write_bytes(payload)
        os.utime(path, (timestamp, timestamp))
    return DemoFolderResult(
        target=target,
        dry_run=dry_run,
        created=tuple(created),
        preserved_existing=tuple(preserved_existing),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a safe demo folder for Smart Organizer.")
    parser.add_argument(
        "--path",
        default=str(PROJECT_ROOT / "demo_files"),
        help="Folder to create or refresh. Defaults to ./demo_files inside the project.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which demo files would be created without changing the filesystem.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = Path(args.path).expanduser()
    result = create_demo_folder(target, dry_run=args.dry_run)
    if result.dry_run:
        print(f"Demo folder dry-run: {target.resolve()}")
    else:
        print(f"Demo folder ready: {result.target.resolve()}")
    print(f"Created demo files: {len(result.created)}")
    print(f"Preserved existing files: {len(result.preserved_existing)}")
    print("Next: streamlit run app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
