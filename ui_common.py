from __future__ import annotations

import csv
import datetime
import json
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Callable, cast

import streamlit as st

from services import UploadedFileData

QUARANTINE_DIRNAME = ".smart_organizer_quarantine"
QUARANTINE_MANIFEST = "manifest.json"


@dataclass(slots=True)
class UIContext:
    processor: Any
    storage: Any
    project_root: Path
    upload_dir: Path
    repo_root: Path
    db_path: Path
    max_upload_bytes: int
    pandas: Any = None
    plt: Any = None


def inject_global_css() -> None:
    st.markdown(
        """
        <style>
          :root {
            --so-bg: #f7faf8;
            --so-surface: rgba(255, 255, 255, 0.92);
            --so-border: rgba(15, 23, 42, 0.10);
            --so-text: #0f172a;
            --so-muted: rgba(15, 23, 42, 0.65);
            --so-accent: #10b981;
            --so-accent-2: #3b82f6;
            --so-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
            --so-radius: 20px;
            --so-primary-border: rgba(16, 185, 129, 0.25);
            --so-secondary-border: rgba(59, 130, 246, 0.22);
          }

          .stApp {
            background: radial-gradient(1200px 600px at 20% -10%, rgba(16, 185, 129, 0.10), transparent 60%),
                        radial-gradient(900px 500px at 90% 0%, rgba(59, 130, 246, 0.10), transparent 55%),
                        var(--so-bg);
            color: var(--so-text);
          }

          section[data-testid="stSidebar"] {
            background: rgba(255, 255, 255, 0.70);
            border-right: 1px solid rgba(15, 23, 42, 0.06);
          }

          .hero-card,
          .primary-action-card,
          .secondary-action-card,
          .status-card {
            background: var(--so-surface);
            border: 1px solid var(--so-border);
            border-radius: var(--so-radius);
            box-shadow: var(--so-shadow);
            padding: 18px 18px;
            margin: 6px 0 14px 0;
          }

          .primary-action-card {
            background: linear-gradient(135deg, rgba(236, 253, 245, 0.98), rgba(255, 251, 235, 0.92));
            border-color: var(--so-primary-border);
          }

          .secondary-action-card {
            background: linear-gradient(135deg, rgba(239, 246, 255, 0.98), rgba(248, 250, 252, 0.92));
            border-color: var(--so-secondary-border);
          }

          .hero-title {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 26px;
            font-weight: 800;
            letter-spacing: -0.02em;
            margin: 0;
          }

          .version-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 10px;
            border-radius: 999px;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.30);
            color: rgba(15, 23, 42, 0.85);
            font-weight: 700;
            font-size: 13px;
            white-space: nowrap;
          }

          .hero-subtitle {
            margin: 8px 0 0 0;
            color: var(--so-muted);
            font-size: 14px;
            line-height: 1.55;
          }

          .feature-chips {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
          }

          .feature-chip {
            display: inline-flex;
            align-items: center;
            padding: 6px 10px;
            border-radius: 999px;
            background: rgba(2, 132, 199, 0.08);
            border: 1px solid rgba(2, 132, 199, 0.20);
            color: rgba(15, 23, 42, 0.85);
            font-weight: 650;
            font-size: 12.5px;
            white-space: nowrap;
          }

          .card-title {
            font-size: 16px;
            font-weight: 800;
            margin: 0 0 8px 0;
          }

          .card-muted {
            color: var(--so-muted);
            font-size: 13px;
            line-height: 1.55;
            margin: 0 0 8px 0;
          }

          .status-metric {
            font-weight: 900;
            font-size: 22px;
            margin: 0;
          }

          .status-label {
            color: var(--so-muted);
            font-size: 12.5px;
            margin-top: 4px;
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def card_open(class_name: str) -> None:
    st.markdown(f'<div class="{class_name}">', unsafe_allow_html=True)


def card_close() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def human_bytes(num_bytes: int | None) -> str:
    if num_bytes is None:
        return "-"
    value = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if value < 1024.0 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024.0
    return f"{int(num_bytes)} B"


def is_debug() -> bool:
    return bool(st.session_state.get("debug_mode", False))


def handle_ui_exception(user_message: str, exc: Exception) -> None:
    if is_debug():
        st.exception(exc)
    else:
        st.error(user_message)


def build_uploaded_file_batch(uploaded_files: list[Any]) -> list[UploadedFileData]:
    return [
        UploadedFileData(
            name=uploaded_file.name,
            content=bytes(uploaded_file.getbuffer()),
            mime_type=str(getattr(uploaded_file, "type", "") or ""),
        )
        for uploaded_file in uploaded_files
    ]


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


def _safe_int(value: object) -> int:
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


def _iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _quarantine_dir(root: Path) -> Path:
    return root / QUARANTINE_DIRNAME


def _quarantine_manifest_path(root: Path) -> Path:
    return _quarantine_dir(root) / QUARANTINE_MANIFEST


def _load_manifest(root: Path) -> dict[str, object]:
    manifest_path = _quarantine_manifest_path(root)
    if not manifest_path.exists():
        return {"items": []}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def _object_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    return []


def _dict_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return cast(dict[str, object], value)
    return {}


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _save_manifest(root: Path, manifest: dict[str, object]) -> None:
    quarantine_dir = _quarantine_dir(root)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    _quarantine_manifest_path(root).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _safe_destination(path: Path) -> Path:
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


def _candidate_reasons(size_bytes: int, stale_days_since_touch: int | None, large_file_bytes: int) -> list[str]:
    reasons: list[str] = []
    if stale_days_since_touch is not None and stale_days_since_touch >= 0:
        reasons.append(f"Unused for {stale_days_since_touch} days")
    if size_bytes >= large_file_bytes:
        reasons.append(f"Large file ({human_bytes(size_bytes)})")
    return reasons


def _recommendation(reasons: list[str]) -> str:
    if not reasons:
        return "Not recommended for automatic handling"
    if len(reasons) >= 2:
        return "Safe to archive"
    if reasons[0].startswith("Unused"):
        return "Safe to archive"
    return "Needs manual review"


def scan_local_folder(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
    large_file_bytes: int = 250 * 1024 * 1024,
    progress_callback: Callable[[int, int], None] | None = None,
) -> dict[str, object]:
    started = time.perf_counter()
    root = Path(folder_path).expanduser()
    records: list[dict[str, object]] = []
    errors: list[str] = []
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_delta = datetime.timedelta(days=max(0, int(stale_days)))
    scanned = 0
    visited = 0

    def append_record(path_obj: Path, stat_result: os.stat_result) -> None:
        nonlocal scanned
        mtime = datetime.datetime.fromtimestamp(stat_result.st_mtime, tz=datetime.timezone.utc)
        atime = datetime.datetime.fromtimestamp(stat_result.st_atime, tz=datetime.timezone.utc)
        age_days = int((now - max(mtime, atime)).days)
        stale_age_days = age_days if stale_days == 0 or (stale_days > 0 and (now - max(mtime, atime)) >= stale_delta) else None
        reasons = _candidate_reasons(int(stat_result.st_size), stale_age_days, int(large_file_bytes))
        records.append(
            {
                "path": str(path_obj),
                "name": path_obj.name,
                "ext": path_obj.suffix.lower(),
                "size_bytes": int(stat_result.st_size),
                "mtime": mtime.isoformat(),
                "atime": atime.isoformat(),
                "days_since_access": age_days,
                "file_kind": infer_local_file_kind(str(path_obj)),
                "is_stale": stale_age_days is not None,
                "is_large": int(stat_result.st_size) >= int(large_file_bytes),
                "candidate_reasons": reasons,
                "recommendation": _recommendation(reasons),
            }
        )
        scanned += 1
        if progress_callback is not None:
            progress_callback(scanned, max_files)

    def on_walk_error(err: OSError) -> None:
        errors.append(f"Scan error: {err}")

    if recursive:
        walker = os.walk(str(root), topdown=True, onerror=on_walk_error)
        for dirpath, dirnames, filenames in walker:
            dirnames[:] = [name for name in dirnames if name != QUARANTINE_DIRNAME]
            for filename in filenames:
                if scanned >= int(max_files):
                    break
                path_obj = Path(dirpath) / filename
                visited += 1
                try:
                    append_record(path_obj, path_obj.stat())
                except PermissionError:
                    errors.append(f"Permission denied: {path_obj}")
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    errors.append(f"Failed to inspect {path_obj}: {exc}")
            if scanned >= int(max_files):
                break
    else:
        try:
            for entry in os.scandir(str(root)):
                if scanned >= int(max_files):
                    break
                if not entry.is_file():
                    continue
                visited += 1
                try:
                    append_record(Path(entry.path), entry.stat())
                except PermissionError:
                    errors.append(f"Permission denied: {entry.path}")
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    errors.append(f"Failed to inspect {entry.path}: {exc}")
        except PermissionError:
            errors.append(f"Permission denied: {root}")

    quarantine_items = list_quarantine_items(str(root))
    stats = {
        "scanned_files": scanned,
        "visited_files": visited,
        "total_bytes": sum(_safe_int(item.get("size_bytes")) for item in records),
        "stale_candidates": sum(1 for item in records if item.get("is_stale")),
        "large_candidates": sum(1 for item in records if item.get("is_large")),
        "quarantine_files": len(quarantine_items),
    }
    return {
        "path": str(root),
        "recursive": bool(recursive),
        "max_files": int(max_files),
        "stale_days": int(stale_days),
        "large_file_bytes": int(large_file_bytes),
        "scanned_at": _iso_now(),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "records": records,
        "errors": errors[:50],
        "stats": stats,
    }


def run_folder_organizer(
    scan_result: dict[str, object],
    selected_paths: list[str],
    *,
    dry_run: bool,
) -> dict[str, object]:
    root = Path(str(scan_result.get("path") or "")).expanduser()
    records = {str(_dict_object(item).get("path")): _dict_object(item) for item in _object_list(scan_result.get("records"))}
    operation_id = uuid.uuid4().hex
    results: list[dict[str, object]] = []
    manifest = _load_manifest(root)
    manifest_items = [_dict_object(item) for item in _object_list(manifest.get("items"))]

    for selected_path in selected_paths:
        record = records.get(selected_path)
        if not record:
            results.append(
                {
                    "original_path": selected_path,
                    "new_path": None,
                    "status": "FAILED",
                    "reason": "Not found in current scan result",
                    "file_size": 0,
                    "last_modified": None,
                    "processed_at": _iso_now(),
                    "error_message": "Selected file is not available in the current scan result.",
                }
            )
            continue

        original_path = Path(selected_path)
        reasons = ", ".join(_string_list(record.get("candidate_reasons"))) or "Selected manually"
        file_size = _safe_int(record.get("size_bytes"))
        last_modified = record.get("mtime")
        if dry_run:
            results.append(
                {
                    "original_path": str(original_path),
                    "new_path": str(_quarantine_dir(root) / operation_id / original_path.name),
                    "status": "SKIPPED",
                    "reason": reasons,
                    "file_size": file_size,
                    "last_modified": last_modified,
                    "processed_at": _iso_now(),
                    "error_message": "Dry-run preview only.",
                }
            )
            continue

        try:
            if not original_path.exists():
                raise FileNotFoundError("Source file no longer exists.")
            try:
                relative_path = original_path.relative_to(root)
            except ValueError:
                relative_path = Path(original_path.name)
            destination = _quarantine_dir(root) / operation_id / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination = _safe_destination(destination)
            shutil.move(str(original_path), str(destination))
            manifest_items.append(
                {
                    "original_path": str(original_path),
                    "quarantine_path": str(destination),
                    "moved_at": _iso_now(),
                    "file_size": file_size,
                    "reason": reasons,
                    "operation_id": operation_id,
                    "last_modified": last_modified,
                    "status": "ACTIVE",
                }
            )
            results.append(
                {
                    "original_path": str(original_path),
                    "new_path": str(destination),
                    "status": "SUCCESS",
                    "reason": reasons,
                    "file_size": file_size,
                    "last_modified": last_modified,
                    "processed_at": _iso_now(),
                    "error_message": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "original_path": str(original_path),
                    "new_path": None,
                    "status": "FAILED",
                    "reason": reasons,
                    "file_size": file_size,
                    "last_modified": last_modified,
                    "processed_at": _iso_now(),
                    "error_message": str(exc) or type(exc).__name__,
                }
            )

    if not dry_run:
        manifest["items"] = manifest_items
        _save_manifest(root, manifest)

    return {
        "operation_id": operation_id,
        "dry_run": dry_run,
        "results": results,
        "summary": {
            "selected": len(selected_paths),
            "success": sum(1 for item in results if item["status"] == "SUCCESS"),
            "failed": sum(1 for item in results if item["status"] == "FAILED"),
            "skipped": sum(1 for item in results if item["status"] == "SKIPPED"),
        },
    }


def list_quarantine_items(folder_path: str) -> list[dict[str, object]]:
    root = Path(folder_path).expanduser()
    manifest = _load_manifest(root)
    items = []
    for item in _object_list(manifest.get("items")):
        item_dict = _dict_object(item)
        if str(item_dict.get("status") or "ACTIVE") == "ACTIVE":
            items.append(item_dict)
    return items


def restore_quarantined_items(folder_path: str, quarantine_paths: list[str]) -> dict[str, object]:
    root = Path(folder_path).expanduser()
    manifest = _load_manifest(root)
    items = [_dict_object(item) for item in _object_list(manifest.get("items"))]
    lookup = {str(item.get("quarantine_path")): item for item in items}
    results: list[dict[str, object]] = []

    for quarantine_path in quarantine_paths:
        item = lookup.get(quarantine_path)
        if item is None:
            results.append(
                {
                    "original_path": None,
                    "new_path": None,
                    "status": "FAILED",
                    "reason": "Manifest entry not found",
                    "file_size": 0,
                    "last_modified": None,
                    "processed_at": _iso_now(),
                    "error_message": "Manifest entry not found.",
                }
            )
            continue
        source = Path(str(item.get("quarantine_path") or ""))
        original = Path(str(item.get("original_path") or ""))
        try:
            if not source.exists():
                raise FileNotFoundError("Quarantined file is missing.")
            destination = _safe_destination(original)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            item["status"] = "RESTORED"
            item["restored_at"] = _iso_now()
            item["restored_path"] = str(destination)
            results.append(
                {
                    "original_path": str(original),
                    "new_path": str(destination),
                    "status": "SUCCESS",
                    "reason": item.get("reason"),
                    "file_size": _safe_int(item.get("file_size")),
                    "last_modified": item.get("last_modified"),
                    "processed_at": _iso_now(),
                    "error_message": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "original_path": str(original) if item.get("original_path") else None,
                    "new_path": None,
                    "status": "FAILED",
                    "reason": item.get("reason"),
                    "file_size": _safe_int(item.get("file_size")),
                    "last_modified": item.get("last_modified"),
                    "processed_at": _iso_now(),
                    "error_message": str(exc) or type(exc).__name__,
                }
            )

    manifest["items"] = items
    _save_manifest(root, manifest)
    return {
        "results": results,
        "summary": {
            "selected": len(quarantine_paths),
            "success": sum(1 for item in results if item["status"] == "SUCCESS"),
            "failed": sum(1 for item in results if item["status"] == "FAILED"),
            "skipped": 0,
        },
    }


def export_folder_report_markdown(
    scan_result: dict[str, object],
    operation_result: dict[str, object] | None = None,
) -> str:
    stats = _dict_object(scan_result.get("stats"))
    rows = [_dict_object(item) for item in _object_list((operation_result or {}).get("results"))]
    lines = [
        "# Smart Organizer Report",
        "",
        f"- Scan path: `{scan_result.get('path')}`",
        f"- Scanned at: {scan_result.get('scanned_at')}",
        f"- Scanned files: {stats.get('scanned_files', 0)}",
        f"- Total size: {human_bytes(_safe_int(stats.get('total_bytes')))}",
        f"- Stale candidates: {stats.get('stale_candidates', 0)}",
        f"- Large file candidates: {stats.get('large_candidates', 0)}",
        f"- Processed files: {len(rows)}",
        f"- Success: {sum(1 for row in rows if row.get('status') == 'SUCCESS')}",
        f"- Failed: {sum(1 for row in rows if row.get('status') == 'FAILED')}",
        f"- Skipped: {sum(1 for row in rows if row.get('status') == 'SKIPPED')}",
        "",
        "| Original path | New path | Size | Last modified | Status | Failure reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("original_path") or "-"),
                    str(row.get("new_path") or "-"),
                    human_bytes(_safe_int(row.get("file_size"))),
                    str(row.get("last_modified") or "-"),
                    str(row.get("status") or "-"),
                    str(row.get("error_message") or "-"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def export_records_csv(records: list[dict[str, object]]) -> str:
    buffer = StringIO()
    fieldnames = [
        "file_id",
        "original_name",
        "file_type",
        "standard_date",
        "main_topic",
        "all_tags",
        "status",
        "manual_override",
        "last_error",
        "created_at",
        "final_path",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for record in records:
        writer.writerow({key: record.get(key) for key in fieldnames})
    return buffer.getvalue()


def export_records_markdown(records: list[dict[str, object]]) -> str:
    lines = [
        "# Filtered Records Export",
        "",
        "| ID | File | Type | Topic | Status | Created at | Last error |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(record.get("file_id") or "-"),
                    str(record.get("original_name") or "-"),
                    str(record.get("file_type") or "-"),
                    str(record.get("main_topic") or "-"),
                    str(record.get("status") or "-"),
                    str(record.get("created_at") or "-"),
                    str(record.get("last_error") or "-"),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"
