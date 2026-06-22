from __future__ import annotations

import datetime
import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from contracts import VideoMetadata
from core_utils import FileUtils

logger = logging.getLogger(__name__)


def sniff_video_container(file_path: str, *, max_bytes: int = 4096) -> tuple[bool, str | None]:
    try:
        with open(file_path, "rb") as handle:
            header = handle.read(max(32, int(max_bytes)))
    except FileNotFoundError as exc:
        return False, f"video container validation failed: file not found: {exc.filename or file_path}"
    except PermissionError as exc:
        return False, f"video container validation failed: permission denied: {exc.filename or file_path}"
    except OSError as exc:
        return False, f"video container validation failed: {exc}"
    if len(header) < 12:
        return False, "video container validation failed: file is too small"
    if header.startswith(b"\x1aE\xdf\xa3"):
        return True, None
    if header.startswith(b"RIFF") and header[8:12] in {b"AVI ", b"WEBP"}:
        return True, None
    if header[4:8] == b"ftyp":
        return True, None
    if header.startswith(b"OggS"):
        return True, None
    return False, "video container validation failed: signature does not match a supported video container"


def detect_ffmpeg_available(
    *,
    run_video_subprocess: Callable[[list[str]], Any],
) -> bool:
    if not shutil.which("ffprobe") or not shutil.which("ffmpeg"):
        return False
    try:
        probe = run_video_subprocess(["ffprobe", "-version"])
        ffmpeg = run_video_subprocess(["ffmpeg", "-version"])
        return probe.returncode == 0 and ffmpeg.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def extract_video_metadata(
    file_path: str,
    *,
    ffmpeg_available: bool,
    timeout_seconds: int,
    run_video_subprocess: Callable[[list[str], int | None], Any],
) -> VideoMetadata:
    result: VideoMetadata = {
        "media_type": "video",
        "duration_seconds": None,
        "width": None,
        "height": None,
        "fps": None,
        "video_codec": None,
        "file_size": None,
        "created_at": None,
        "modified_at": None,
        "ffprobe_error": None,
    }

    if not ffmpeg_available:
        result["ffprobe_error"] = "ffprobe is unavailable; video metadata could not be collected."
        return result

    try:
        import json

        with suppress(OSError):
            result["file_size"] = os.path.getsize(file_path)
        with suppress(OSError):
            mtime = os.path.getmtime(file_path)
            result["modified_at"] = datetime.datetime.fromtimestamp(mtime, tz=datetime.UTC).isoformat(
                timespec="seconds"
            )

        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", file_path]
        try:
            proc = run_video_subprocess(cmd, timeout_seconds)
            if proc.returncode != 0:
                result["ffprobe_error"] = (proc.stderr or "").strip() or "ffprobe failed"
                return result

            data = json.loads(proc.stdout or "{}")
            fmt = data.get("format") or {}
            streams = data.get("streams") or []

            duration = fmt.get("duration")
            if duration is not None:
                with suppress(TypeError, ValueError):
                    result["duration_seconds"] = float(duration)

            video_stream = next((stream for stream in streams if (stream.get("codec_type") or "") == "video"), None)
            if isinstance(video_stream, dict):
                result["width"] = video_stream.get("width")
                result["height"] = video_stream.get("height")
                result["video_codec"] = video_stream.get("codec_name")
                frame_rate = video_stream.get("r_frame_rate") or ""
                if isinstance(frame_rate, str) and "/" in frame_rate:
                    try:
                        numerator, denominator = frame_rate.split("/", 1)
                        result["fps"] = float(numerator) / float(denominator) if float(denominator) else None
                    except (TypeError, ValueError, ZeroDivisionError):
                        pass
        except subprocess.TimeoutExpired:
            result["ffprobe_error"] = f"ffprobe timed out after {timeout_seconds}s"
        except (json.JSONDecodeError, OSError, subprocess.SubprocessError, ValueError) as exc:
            result["ffprobe_error"] = f"ffprobe failed: {exc}"
    except (ImportError, OSError) as exc:
        result["ffprobe_error"] = str(exc)
    return result


def generate_video_thumbnail(
    file_path: str,
    *,
    ffmpeg_available: bool,
    timeout_seconds: int,
    thumb_percent: float = 0.5,
    duration_seconds: float | None = None,
) -> tuple[str | None, str | None]:
    if not ffmpeg_available:
        return None, "ffmpeg is unavailable; thumbnail generation was skipped."
    try:
        base_preview_path = FileUtils.build_preview_path(file_path)
        preview_path = os.path.splitext(base_preview_path)[0] + ".jpg"
        os.makedirs(os.path.dirname(preview_path), exist_ok=True)
        try:
            normalized_percent = float(thumb_percent)
        except (TypeError, ValueError):
            normalized_percent = 0.5
        normalized_percent = min(1.0, max(0.0, normalized_percent))
        seek_seconds = 1.0
        if duration_seconds is not None:
            try:
                seek_seconds = max(0.0, float(duration_seconds) * normalized_percent)
            except (TypeError, ValueError):
                seek_seconds = 1.0
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{seek_seconds:.3f}",
            "-i",
            file_path,
            "-vf",
            "scale=320:-1",
            "-frames:v",
            "1",
            "-q:v",
            "2",
            preview_path,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                timeout=max(1, int(timeout_seconds or 10)),
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
            if os.path.exists(preview_path):
                return preview_path, None
            stderr = (proc.stderr or "").strip()
            if stderr:
                return None, stderr[:200]
            return None, "ffmpeg finished without creating a thumbnail."
        except subprocess.TimeoutExpired:
            return None, f"ffmpeg thumbnail generation timeout after {timeout_seconds}s"
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return None, f"ffmpeg failed: {str(exc)[:200]}"
    except OSError as exc:
        return None, str(exc)[:200]
