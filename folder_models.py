from __future__ import annotations

import datetime
import json
import os
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypedDict, cast

from supported_formats import SUPPORTED_VIDEO_SUFFIXES

QUARANTINE_DIRNAME = ".smart_organizer_quarantine"
QUARANTINE_MANIFEST = "manifest.json"

FolderActionStatus = Literal["SUCCESS", "FAILED", "SKIPPED"]


class QuarantineStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    PREVIEWED = "PREVIEWED"
    MOVING = "MOVING"
    QUARANTINED = "QUARANTINED"
    RESTORED = "RESTORED"
    FAILED = "FAILED"


ACTIVE_QUARANTINE_STATUSES = {QuarantineStatus.MOVING.value, QuarantineStatus.QUARANTINED.value}


class RiskLevel(StrEnum):
    SAFE_TO_REVIEW = "safe_to_review"
    NEEDS_MANUAL_CHECK = "needs_manual_check"
    DO_NOT_TOUCH = "do_not_touch"


def is_relative_to_path(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class FolderOrganizerError(RuntimeError):
    """Base error for folder cleanup flows."""


class ScanPathError(FolderOrganizerError):
    """Raised when a scan target is invalid or inaccessible."""


class ManifestCompatibilityError(FolderOrganizerError):
    """Raised when a quarantine manifest is unusable."""


@dataclass(slots=True)
class FolderActionResult:
    success: bool
    source: str
    target: str | None = None
    error: str | None = None


@dataclass(slots=True)
class FolderScanRecord:
    path: str
    name: str
    ext: str
    size_bytes: int
    mtime: str
    atime: str
    days_since_access: int
    file_kind: str
    is_stale: bool
    is_large: bool
    candidate_reasons: list[str]
    recommendation: str
    category: str = "general"
    confidence: float = 0.0
    risk_level: str = RiskLevel.DO_NOT_TOUCH.value
    reason_codes: list[str] | None = None
    file_age_score: float = 0.0
    size_score: float = 0.0
    duplicate_score: float = 0.0
    extension_risk_score: float = 0.0

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        if payload["reason_codes"] is None:
            payload["reason_codes"] = []
        return payload


@dataclass(slots=True)
class FolderScanStats:
    scanned_files: int
    visited_files: int
    total_bytes: int
    stale_candidates: int
    large_candidates: int
    quarantine_files: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FolderScanResult:
    path: str
    recursive: bool
    max_files: int
    stale_days: int
    large_file_bytes: int
    scanned_at: str
    elapsed_seconds: float
    records: list[FolderScanRecord]
    errors: list[str]
    stats: FolderScanStats

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "recursive": self.recursive,
            "max_files": self.max_files,
            "stale_days": self.stale_days,
            "large_file_bytes": self.large_file_bytes,
            "scanned_at": self.scanned_at,
            "elapsed_seconds": self.elapsed_seconds,
            "records": [record.to_dict() for record in self.records],
            "errors": list(self.errors),
            "stats": self.stats.to_dict(),
        }


@dataclass(slots=True)
class FolderOperationRow:
    original_path: str | None
    new_path: str | None
    status: FolderActionStatus
    reason: str | None
    file_size: int
    last_modified: str | None
    processed_at: str
    error_message: str | None
    operation_id: str | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FolderOperationSummary:
    selected: int
    success: int
    failed: int
    skipped: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class FolderOperationResult:
    operation_id: str | None
    dry_run: bool
    results: list[FolderOperationRow]
    summary: FolderOperationSummary

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "dry_run": self.dry_run,
            "results": [row.to_dict() for row in self.results],
            "summary": self.summary.to_dict(),
        }


class ManifestItem(TypedDict, total=False):
    original_path: str
    quarantine_path: str
    moved_at: str
    file_size: int
    reason: str
    operation_id: str
    last_modified: str | None
    status: str
    restored_at: str
    restored_path: str
    last_error: str


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
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def infer_local_file_kind(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png"}:
        return "photo"
    if ext in SUPPORTED_VIDEO_SUFFIXES:
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


def _normalize_manifest_items(items: object) -> list[ManifestItem]:
    normalized: list[ManifestItem] = []
    for value in object_list(items):
        item = dict_object(value)
        quarantine_path = str(item.get("quarantine_path") or item.get("new_path") or "").strip()
        original_path = str(item.get("original_path") or "").strip()
        if not quarantine_path:
            continue
        status = str(item.get("status") or "QUARANTINED").strip().upper()
        if status == "ACTIVE":
            status = QuarantineStatus.QUARANTINED.value
        if status not in {member.value for member in QuarantineStatus}:
            status = QuarantineStatus.FAILED.value
        normalized.append(
            {
                "original_path": original_path,
                "quarantine_path": quarantine_path,
                "moved_at": str(item.get("moved_at") or item.get("processed_at") or ""),
                "file_size": safe_int(item.get("file_size")),
                "reason": str(item.get("reason") or ""),
                "operation_id": str(item.get("operation_id") or ""),
                "last_modified": str(item.get("last_modified") or "") or None,
                "status": status,
                "restored_at": str(item.get("restored_at") or ""),
                "restored_path": str(item.get("restored_path") or ""),
                "last_error": str(item.get("last_error") or ""),
            }
        )
    return normalized


def load_manifest(root: Path) -> dict[str, object]:
    manifest_path = quarantine_manifest_path(root)
    if not manifest_path.exists():
        return {"items": []}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestCompatibilityError(f"Manifest is not valid JSON: {exc}") from exc
    except OSError as exc:
        raise ManifestCompatibilityError(f"Failed to read manifest: {exc}") from exc

    if not isinstance(raw, dict):
        raise ManifestCompatibilityError("Manifest root must be a JSON object.")

    return {"items": _normalize_manifest_items(raw.get("items"))}


def save_manifest(root: Path, manifest: dict[str, object]) -> None:
    target_dir = quarantine_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    normalized = {"items": _normalize_manifest_items(manifest.get("items"))}
    manifest_path = quarantine_manifest_path(root)
    tmp_path = manifest_path.with_name(f"{manifest_path.name}.tmp")
    payload = json.dumps(normalized, ensure_ascii=False, indent=2)

    try:
        if tmp_path.exists():
            tmp_path.unlink()
        with tmp_path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, manifest_path)
    except OSError as exc:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        raise ManifestCompatibilityError(f"Failed to atomically save manifest: {exc}") from exc


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
