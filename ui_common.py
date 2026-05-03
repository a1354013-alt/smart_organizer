from __future__ import annotations

import datetime
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from services import UploadedFileData


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

          div[data-testid="stMainBlockContainer"] {
            padding-top: 1.2rem;
            padding-bottom: 2rem;
          }

          .stButton > button {
            border-radius: 14px;
            border: 1px solid rgba(15, 23, 42, 0.12);
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
          }

          .stButton > button[kind="primary"] {
            background: rgba(16, 185, 129, 0.85);
            border: 1px solid rgba(16, 185, 129, 0.30);
          }

          .stButton > button[kind="primary"]:hover {
            background: rgba(16, 185, 129, 0.92);
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
    if ext in {".mp4", ".mov", ".mkv"}:
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


def scan_local_folder(
    folder_path: str,
    *,
    recursive: bool,
    max_files: int,
    stale_days: int,
) -> dict[str, object]:
    started = time.perf_counter()
    root = Path(folder_path).expanduser()
    records: list[dict[str, object]] = []
    errors: list[str] = []
    now = datetime.datetime.now(datetime.timezone.utc)
    stale_delta = datetime.timedelta(days=max(0, int(stale_days)))
    scanned = 0

    def append_record(path_obj: Path, stat_result: os.stat_result) -> None:
        nonlocal scanned
        mtime = datetime.datetime.fromtimestamp(stat_result.st_mtime, tz=datetime.timezone.utc)
        is_stale_file = (now - mtime) >= stale_delta if stale_days > 0 else False
        records.append(
            {
                "path": str(path_obj),
                "name": path_obj.name,
                "ext": path_obj.suffix.lower(),
                "size_bytes": int(stat_result.st_size),
                "mtime": mtime.isoformat(),
                "file_kind": infer_local_file_kind(str(path_obj)),
                "is_stale": bool(is_stale_file),
            }
        )
        scanned += 1

    def on_walk_error(err: OSError) -> None:
        errors.append(f"掃描資料夾失敗：{err}")

    if recursive:
        walker = os.walk(str(root), topdown=True, onerror=on_walk_error)
        for dirpath, _dirnames, filenames in walker:
            if scanned >= int(max_files):
                break
            for filename in filenames:
                if scanned >= int(max_files):
                    break
                path_obj = Path(dirpath) / filename
                try:
                    append_record(path_obj, path_obj.stat())
                except PermissionError:
                    errors.append(f"權限不足：{path_obj}")
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    errors.append(f"讀取失敗：{path_obj}（{exc}）")
    else:
        try:
            for entry in os.scandir(str(root)):
                if scanned >= int(max_files):
                    break
                if not entry.is_file():
                    continue
                try:
                    append_record(Path(entry.path), entry.stat())
                except PermissionError:
                    errors.append(f"權限不足：{entry.path}")
                except FileNotFoundError:
                    continue
                except Exception as exc:
                    errors.append(f"讀取失敗：{entry.path}（{exc}）")
        except PermissionError:
            errors.append(f"權限不足：{root}")

    stats = {
        "scanned_files": scanned,
        "total_bytes": sum(_safe_int(item.get("size_bytes")) for item in records),
        "stale_candidates": sum(1 for item in records if item.get("is_stale")),
    }
    return {
        "path": str(root),
        "recursive": bool(recursive),
        "max_files": int(max_files),
        "stale_days": int(stale_days),
        "scanned_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "records": records,
        "errors": errors[:50],
        "stats": stats,
    }
