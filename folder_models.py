from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import cast

QUARANTINE_DIRNAME = ".smart_organizer_quarantine"
QUARANTINE_MANIFEST = "manifest.json"


def human_bytes(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "-"
    value = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{int(num_bytes)} B"


def safe_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def infer_local_file_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png"}:
        return "photo"
    if ext in {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}:
        return "video"
    if ext == ".pdf":
        return "document"
    if ext:
        return "document"
    return "unknown"


def quarantine_dir(root: Path) -> Path:
    return root / QUARANTINE_DIRNAME


def quarantine_manifest_path(root: Path) -> Path:
    return quarantine_dir(root) / QUARANTINE_MANIFEST


def load_manifest(root: Path) -> dict[str, object]:
    manifest_path = quarantine_manifest_path(root)
    if not manifest_path.exists():
        return {"items": []}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def object_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def dict_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


def string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def save_manifest(root: Path, manifest: dict[str, object]) -> None:
    target_dir = quarantine_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    quarantine_manifest_path(root).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def safe_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(1, 1000):
        candidate = parent / f"{stem}__{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Unable to find safe destination for {path}")
