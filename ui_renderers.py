from __future__ import annotations

from typing import Any

import streamlit as st

from contracts import ExtractedMetadata


def _format_duration_mmss(duration_seconds: object) -> str:
    if duration_seconds is None:
        return "N/A"
    try:
        seconds = float(duration_seconds)
    except (TypeError, ValueError):
        return "N/A"
    if seconds < 0:
        return "N/A"
    minutes = int(seconds // 60)
    remainder = int(seconds % 60)
    return f"{minutes:02d}:{remainder:02d}"


def _format_file_size(size_bytes: object) -> str:
    if size_bytes is None:
        return "N/A"
    try:
        size = float(size_bytes)
    except (TypeError, ValueError):
        return "N/A"
    if size < 0:
        return "N/A"
    mb = size / (1024 * 1024)
    if mb >= 1:
        return f"{mb:.1f} MB"
    kb = size / 1024
    return f"{kb:.1f} KB"


def _get_video_meta(metadata: ExtractedMetadata | dict[str, Any]) -> dict[str, Any]:
    md = dict(metadata or {})
    return dict(md.get("video") or md.get("extra") or {})


def render_dependency_status(deps: dict[str, Any]) -> None:
    python_deps = deps.get("python") if isinstance(deps, dict) else None
    system_deps = deps.get("system") if isinstance(deps, dict) else None
    config = deps.get("config") if isinstance(deps, dict) else None

    st.write("**Python 套件**")
    if isinstance(python_deps, dict) and python_deps:
        st.json(python_deps)
    else:
        st.caption("無資料")

    st.write("**系統依賴**")
    if isinstance(system_deps, dict) and system_deps:
        st.json(system_deps)
    else:
        st.caption("無資料")

    st.write("**設定**")
    if isinstance(config, dict) and config:
        st.json(config)
    else:
        st.caption("無資料")


def render_video_details(metadata: ExtractedMetadata | dict[str, Any]) -> None:
    video = _get_video_meta(metadata)

    st.write(f"**長度**: {_format_duration_mmss(video.get('duration_seconds'))}")

    width = video.get("width")
    height = video.get("height")
    if width is not None and height is not None:
        st.write(f"**解析度**: {width} x {height}")
    else:
        st.write("**解析度**: N/A")

    fps = video.get("fps")
    if fps is not None:
        try:
            st.write(f"**FPS**: {int(round(float(fps)))}")
        except (TypeError, ValueError):
            st.write("**FPS**: N/A")
    else:
        st.write("**FPS**: N/A")

    codec = video.get("video_codec")
    if codec:
        codec_display = codec.upper() if isinstance(codec, str) else str(codec)
        st.write(f"**Codec**: {codec_display}")
    else:
        st.write("**Codec**: N/A")

    st.write(f"**檔案大小**: {_format_file_size(video.get('file_size'))}")

    ffprobe_error = video.get("ffprobe_error")
    if ffprobe_error:
        st.warning(f"影片 metadata 取得失敗：{ffprobe_error}")

    thumb_error = video.get("thumbnail_error")
    if thumb_error:
        st.warning(f"影片縮圖產生失敗：{thumb_error}")

