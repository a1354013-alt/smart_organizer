from __future__ import annotations

import math
from typing import Any, Literal, NotRequired, TypeAlias, TypedDict, cast

FileType: TypeAlias = Literal["document", "photo", "video", "unknown"]
RecordStatus: TypeAlias = Literal["PENDING", "PROCESSED", "MOVING", "COMPLETED", "MISSING", "BROKEN"]
DecisionSource: TypeAlias = Literal["RULE", "MANUAL_OVERRIDE", "RULE_RECLASSIFY", "RECOVERY"]
OCRStatus: TypeAlias = Literal["disabled", "success", "unavailable", "failed", "timeout", "empty_text"]

METADATA_REQUIRED_KEYS = {
    "file_type",
    "standard_date",
    "extracted_text",
    "is_scanned",
    "preview_path",
    "ocr_status",
    "ocr_error",
    "notes",
}
METADATA_RESERVED_KEYS = METADATA_REQUIRED_KEYS | {"video", "extra"}
LEGACY_VIDEO_EXTRA_KEYS = {
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
MAX_EXTRACTED_TEXT_LENGTH = 20000
MAX_PATH_LENGTH = 2048
MAX_ERROR_LENGTH = 300
MAX_NOTE_LENGTH = 300
MAX_NOTES_COUNT = 50
MAX_VIDEO_CODEC_LENGTH = 120
MAX_TIMESTAMP_LENGTH = 64


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
    ocr_status: NotRequired[OCRStatus | None]
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


def _normalize_text(value: object, *, max_length: int, allow_empty: bool = True) -> str | None:
    if value is None:
        return "" if allow_empty else None
    text = str(value).strip()
    if not text:
        return "" if allow_empty else None
    return text[:max_length]


def _normalize_bool(value: object) -> bool:
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"", "0", "false", "no", "off", "none", "null"}:
            return False
        if lowered in {"1", "true", "yes", "on"}:
            return True
    return bool(value)


def _normalize_int(value: object, *, min_value: int = 0, max_value: int | None = None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    number = int(parsed)
    if number < min_value:
        return None
    if max_value is not None and number > max_value:
        return None
    return number


def _normalize_float(value: object, *, min_value: float = 0.0, max_value: float | None = None) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number < min_value:
        return None
    if max_value is not None and number > max_value:
        return None
    return number


def _normalize_ocr_status(value: object) -> OCRStatus | None:
    raw = str(value or "").strip().lower()
    if raw in {"disabled", "success", "unavailable", "failed", "timeout", "empty_text"}:
        return cast(OCRStatus, raw)
    return None


def _normalize_notes(value: object) -> list[str]:
    raw_items = value if isinstance(value, list) else ([] if value in (None, "") else [value])
    notes: list[str] = []
    for item in raw_items:
        normalized = _normalize_text(item, max_length=MAX_NOTE_LENGTH, allow_empty=False)
        if normalized is None:
            continue
        notes.append(normalized)
        if len(notes) >= MAX_NOTES_COUNT:
            break
    return notes


def _normalize_extra(
    extra: dict[str, Any],
    *,
    file_type: FileType,
    raw_video: object,
) -> tuple[dict[str, Any], object]:
    if raw_video is None and file_type == "video":
        legacy_keys = {key for key in LEGACY_VIDEO_EXTRA_KEYS if key in extra}
        if legacy_keys:
            raw_video = {key: extra[key] for key in legacy_keys}

    overlap = sorted(set(extra.keys()) & METADATA_RESERVED_KEYS)
    if overlap:
        raise ValueError(f"metadata.extra must not redefine contract keys: {', '.join(overlap)}")

    normalized_extra = {
        str(key): value
        for key, value in extra.items()
        if str(key) not in LEGACY_VIDEO_EXTRA_KEYS
    }
    return normalized_extra, raw_video


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

    ft_raw = str(metadata.get("file_type") or "unknown")
    if ft_raw in {"document", "photo", "video", "unknown"}:
        file_type: FileType = cast(FileType, ft_raw)
    else:
        file_type = "unknown"

    raw_video = metadata.get("video")
    extra, raw_video = _normalize_extra(extra, file_type=file_type, raw_video=raw_video)

    normalized: ExtractedMetadata = {
        "file_type": file_type,
        "standard_date": _normalize_text(metadata.get("standard_date"), max_length=32) or "",
        "extracted_text": _normalize_text(metadata.get("extracted_text"), max_length=MAX_EXTRACTED_TEXT_LENGTH) or "",
        "is_scanned": _normalize_bool(metadata.get("is_scanned", False)),
        "preview_path": _normalize_text(metadata.get("preview_path"), max_length=MAX_PATH_LENGTH, allow_empty=False),
        "ocr_error": _normalize_text(metadata.get("ocr_error"), max_length=MAX_ERROR_LENGTH, allow_empty=False),
        "notes": _normalize_notes(metadata.get("notes")),
    }
    ocr_status = _normalize_ocr_status(metadata.get("ocr_status"))
    if ocr_status is not None:
        normalized["ocr_status"] = ocr_status

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
            "duration_seconds": cast(Any, _normalize_float(video_dict.get("duration_seconds"), min_value=0.0, max_value=31_536_000.0)),
            "width": cast(Any, _normalize_int(video_dict.get("width"), min_value=1, max_value=100_000)),
            "height": cast(Any, _normalize_int(video_dict.get("height"), min_value=1, max_value=100_000)),
            "fps": cast(Any, _normalize_float(video_dict.get("fps"), min_value=0.0, max_value=1_000.0)),
            "video_codec": cast(Any, _normalize_text(video_dict.get("video_codec"), max_length=MAX_VIDEO_CODEC_LENGTH, allow_empty=False)),
            "file_size": cast(Any, _normalize_int(video_dict.get("file_size"), min_value=0, max_value=10**15)),
            "created_at": cast(Any, _normalize_text(video_dict.get("created_at"), max_length=MAX_TIMESTAMP_LENGTH, allow_empty=False)),
            "modified_at": cast(Any, _normalize_text(video_dict.get("modified_at"), max_length=MAX_TIMESTAMP_LENGTH, allow_empty=False)),
            "ffprobe_error": cast(Any, _normalize_text(video_dict.get("ffprobe_error"), max_length=MAX_ERROR_LENGTH, allow_empty=False)),
            "thumbnail_error": cast(Any, _normalize_text(video_dict.get("thumbnail_error"), max_length=MAX_ERROR_LENGTH, allow_empty=False)),
        }
    if extra:
        normalized["extra"] = extra
    return normalized
