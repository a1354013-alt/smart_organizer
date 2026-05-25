from __future__ import annotations

from typing import Any

import streamlit as st

from contracts import ExtractedMetadata
from i18n import t
from ui_common import safe_display_text


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _na() -> str:
    return t("renderers.video.not_available")


def _format_duration_mmss(duration_seconds: object) -> str:
    if duration_seconds is None:
        return _na()
    seconds = _to_float(duration_seconds)
    if seconds is None or seconds < 0:
        return _na()
    minutes = int(seconds // 60)
    remainder = int(seconds % 60)
    return f"{minutes:02d}:{remainder:02d}"


def _format_file_size(size_bytes: object) -> str:
    if size_bytes is None:
        return _na()
    size = _to_float(size_bytes)
    if size is None or size < 0:
        return _na()
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

    for heading, payload in (
        (t("renderers.dependencies.python"), python_deps),
        (t("renderers.dependencies.system"), system_deps),
        (t("renderers.dependencies.config"), config),
    ):
        st.write(f"**{heading}**")
        if isinstance(payload, dict) and payload:
            st.json(payload)
        else:
            st.caption(t("renderers.dependencies.empty"))


def render_video_details(metadata: ExtractedMetadata | dict[str, Any]) -> None:
    video = _get_video_meta(metadata)

    st.write(f"**{t('renderers.video.duration')}**: {_format_duration_mmss(video.get('duration_seconds'))}")

    width = video.get("width")
    height = video.get("height")
    if width is not None and height is not None:
        st.write(f"**{t('renderers.video.resolution')}**: {width} x {height}")
    else:
        st.write(f"**{t('renderers.video.resolution')}**: {_na()}")

    fps = video.get("fps")
    if fps is not None:
        try:
            st.write(f"**{t('renderers.video.fps')}**: {int(round(float(fps)))}")
        except (TypeError, ValueError):
            st.write(f"**{t('renderers.video.fps')}**: {_na()}")
    else:
        st.write(f"**{t('renderers.video.fps')}**: {_na()}")

    codec = video.get("video_codec")
    if codec:
        codec_display = codec.upper() if isinstance(codec, str) else str(codec)
        st.write(f"**{t('renderers.video.codec')}**: {safe_display_text(codec_display)}")
    else:
        st.write(f"**{t('renderers.video.codec')}**: {_na()}")

    st.write(f"**{t('renderers.video.file_size')}**: {_format_file_size(video.get('file_size'))}")

    ffprobe_error = video.get("ffprobe_error")
    if ffprobe_error:
        st.warning(t("renderers.video.degraded", message=safe_display_text(ffprobe_error)))

    thumb_error = video.get("thumbnail_error")
    if thumb_error:
        st.warning(t("renderers.video.thumbnail_unavailable", message=safe_display_text(thumb_error)))
