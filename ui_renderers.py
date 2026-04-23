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
    st.write("Python 套件：", deps.get("python", {}))
    st.write("系統依賴：", deps.get("system", {}))
    st.write("設定：", deps.get("config", {}))


def render_video_details(metadata: ExtractedMetadata | dict[str, Any]) -> None:
    video = _get_video_meta(metadata)

    st.write(f"**時長**: {_format_duration_mmss(video.get('duration_seconds'))}")

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
        st.write(f"**編碼**: {codec_display}")
    else:
        st.write("**編碼**: N/A")

    st.write(f"**大小**: {_format_file_size(video.get('file_size'))}")

    thumb_error = video.get("thumbnail_error")
    if thumb_error:
        st.warning(f"縮圖提示：{thumb_error}")

