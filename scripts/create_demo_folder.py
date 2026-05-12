from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


DEMO_FILES: tuple[tuple[str, bytes, int], ...] = (
    ("old_invoice_2022.txt", b"Invoice 2022\nVendor: Demo Co.\nAmount: 1280\n", 760),
    ("old_large_video.mp4.fake", b"fake video placeholder\n" * 128, 900),
    ("screenshot_2021.png.fake", b"fake screenshot placeholder\n", 1100),
    ("recent_notes.txt", b"Recent meeting notes. Keep handy.\n", 3),
    ("duplicate_a.txt", b"duplicate content demo\n", 500),
    ("duplicate_b.txt", b"duplicate content demo\n", 500),
    ("readme_keep.txt", b"Keep this file to show the do-not-touch risk label.\n", 120),
)


def create_demo_folder(target: Path) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    for name, payload, age_days in DEMO_FILES:
        path = target / name
        if not path.exists():
            path.write_bytes(payload)
        timestamp = (now - timedelta(days=age_days)).timestamp()
        os.utime(path, (timestamp, timestamp))
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a safe demo folder for Smart Organizer.")
    parser.add_argument(
        "--path",
        default=str(PROJECT_ROOT / "demo_files"),
        help="Folder to create or refresh. Defaults to ./demo_files inside the project.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    target = Path(args.path).expanduser()
    demo_path = create_demo_folder(target)
    print(f"Demo folder ready: {demo_path.resolve()}")
    print("Next: streamlit run app.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
