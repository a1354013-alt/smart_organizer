from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict, TypeAlias, cast

FileType: TypeAlias = Literal["document", "photo", "video", "unknown"]
RecordStatus: TypeAlias = Literal["PENDING", "PROCESSED", "MOVING", "COMPLETED", "MISSING", "BROKEN"]
DecisionSource: TypeAlias = Literal["RULE", "MANUAL_OVERRIDE", "RULE_RECLASSIFY", "RECOVERY"]

METADATA_REQUIRED_KEYS = {
    "file_type",
    "standard_date",
    "extracted_text",
    "is_scanned",
    "preview_path",
    "ocr_error",
    "notes",
}


class VideoMetadata(TypedDict, total=False):
    """
    Stable cross-module video metadata contract (Phase 1).

    This is container-level metadata from ffprobe plus thumbnail status.
    We do NOT do video content understanding.
    """

    media_type: Literal["video"]
    duration_seconds: float | None
    width: int | None
    height: int | None
    fps: float | None
    video_codec: str | None
    file_size: int | None
    created_at: str | None
    modified_at: str | None
    ffprobe_error: str | None
    thumbnail_error: str | None


class ExtractedMetadata(TypedDict):
    """
    Cross-module metadata contract.

    Keep keys stable to avoid "magic keys" drifting across core/services/app/storage.
    """

    file_type: FileType
    standard_date: str
    extracted_text: str
    is_scanned: bool
    preview_path: str | None
    ocr_error: str | None
    notes: list[str]

    # File-type specific stable sub-contracts.
    video: NotRequired[VideoMetadata]

    # Optional local extension bag (non-contract).
    #
    # IMPORTANT:
    # - Do NOT introduce cross-module dependencies on keys inside `extra`.
    # - Legacy note: older versions stored video fields inside `extra`; we still
    #   accept that shape for backward compatibility, but new code should use
    #   `metadata["video"]` instead.
    extra: NotRequired[dict[str, Any]]


class DecisionHistory(TypedDict, total=False):
    decision_source: DecisionSource
    decision_updated_at: str
    last_manual_topic: str | None
    last_manual_reason: str | None


def validate_extracted_metadata(raw: ExtractedMetadata | dict[str, Any]) -> ExtractedMetadata:
    """
    Normalize and validate the cross-module metadata contract.

    `extra` is explicitly *not* a place for fields that other modules depend on.
    If a future change needs a cross-module field, promote it into `ExtractedMetadata`
    (e.g., the `video` sub-contract).
    """
    metadata = dict(raw or {})
    extra = metadata.get("extra")
    if extra is None:
        extra = {}
    if not isinstance(extra, dict):
        raise TypeError("metadata.extra must be a dict when provided")

    overlap = sorted(set(extra.keys()) & (METADATA_REQUIRED_KEYS | {"video"}))
    if overlap:
        raise ValueError(f"metadata.extra must not redefine contract keys: {', '.join(overlap)}")

    notes = metadata.get("notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]

    ft_raw = str(metadata.get("file_type") or "unknown")
    if ft_raw in {"document", "photo", "video", "unknown"}:
        file_type: FileType = cast(FileType, ft_raw)
    else:
        file_type = "unknown"

    normalized: ExtractedMetadata = {
        "file_type": file_type,
        "standard_date": str(metadata.get("standard_date") or ""),
        "extracted_text": str(metadata.get("extracted_text") or ""),
        "is_scanned": bool(metadata.get("is_scanned", False)),
        "preview_path": metadata.get("preview_path"),
        "ocr_error": metadata.get("ocr_error"),
        "notes": [str(item) for item in notes],
    }

    raw_video = metadata.get("video")
    if raw_video is None and file_type == "video":
        legacy_video_keys = {
            "media_type",
            "duration_seconds",
            "width",
            "height",
            "fps",
            "video_codec",
            "file_size",
            "created_at",
            "modified_at",
            "thumbnail_error",
            "ffprobe_error",
            "error",
        }
        if any(k in extra for k in legacy_video_keys):
            raw_video = extra

    if file_type == "video":
        video_dict: dict[str, Any]
        if raw_video is None:
            video_dict = {}
        elif isinstance(raw_video, dict):
            video_dict = dict(raw_video)
        else:
            raise TypeError("metadata.video must be a dict when provided")

        if "ffprobe_error" not in video_dict and "error" in video_dict:
            video_dict["ffprobe_error"] = video_dict.get("error")

        normalized["video"] = {
            "media_type": "video",
            "duration_seconds": cast(Any, video_dict.get("duration_seconds")),
            "width": cast(Any, video_dict.get("width")),
            "height": cast(Any, video_dict.get("height")),
            "fps": cast(Any, video_dict.get("fps")),
            "video_codec": cast(Any, video_dict.get("video_codec")),
            "file_size": cast(Any, video_dict.get("file_size")),
            "created_at": cast(Any, video_dict.get("created_at")),
            "modified_at": cast(Any, video_dict.get("modified_at")),
            "ffprobe_error": cast(Any, video_dict.get("ffprobe_error")),
            "thumbnail_error": cast(Any, video_dict.get("thumbnail_error")),
        }
    if extra:
        normalized["extra"] = extra
    return normalized
