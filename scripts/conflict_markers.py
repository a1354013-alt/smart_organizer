from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from zipfile import ZipFile

CONFLICT_MARKERS = ("<" * 7, "=" * 7, ">" * 7)
BINARY_SAMPLE_SIZE = 4096
TEXT_EXTENSIONS = {
    ".bat",
    ".cfg",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".py",
    ".ps1",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def _looks_binary(payload: bytes) -> bool:
    return b"\0" in payload


def _decode_text(payload: bytes) -> str | None:
    if _looks_binary(payload[:BINARY_SAMPLE_SIZE]):
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return payload.decode("utf-8-sig")
        except UnicodeDecodeError:
            return None


def text_has_conflict_markers(text: str) -> bool:
    return any(marker in text for marker in CONFLICT_MARKERS)


def find_conflict_markers_in_bytes(name: str, payload: bytes) -> str | None:
    suffix = Path(name).suffix.lower()
    if suffix and suffix not in TEXT_EXTENSIONS:
        return None
    text = _decode_text(payload)
    if text is None:
        return None
    return name if text_has_conflict_markers(text) else None


def find_conflict_markers_in_files(paths: Iterable[Path]) -> list[str]:
    hits: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        hit = find_conflict_markers_in_bytes(str(path), path.read_bytes())
        if hit is not None:
            hits.append(str(path))
    return sorted(hits)


def find_conflict_markers_in_zip(zip_path: Path) -> list[str]:
    hits: list[str] = []
    with ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            payload = archive.read(info)
            hit = find_conflict_markers_in_bytes(info.filename, payload)
            if hit is not None:
                hits.append(hit)
    return sorted(hits)
