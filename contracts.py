from __future__ import annotations

from typing import Any, NotRequired, TypedDict

METADATA_REQUIRED_KEYS = {
    "file_type",
    "standard_date",
    "extracted_text",
    "is_scanned",
    "preview_path",
    "ocr_error",
    "notes",
}


class ExtractedMetadata(TypedDict):
    """
    Cross-module metadata contract.

    Keep keys stable to avoid "magic keys" drifting across core/services/app/storage.
    """

    file_type: str  # "document" | "photo" | "unknown"
    standard_date: str
    extracted_text: str
    is_scanned: bool
    preview_path: str | None
    ocr_error: str | None
    notes: list[str]

    # Optional extras (may be extended, but should remain backward compatible).
    # IMPORTANT: any field that is read across module boundaries MUST be promoted
    # into the top-level contract above instead of being stuffed into `extra`.
    extra: NotRequired[dict[str, Any]]


class DecisionHistory(TypedDict, total=False):
    decision_source: str  # e.g. "RULE", "MANUAL_OVERRIDE", "RULE_RECLASSIFY", "RECOVERY"
    decision_updated_at: str
    last_manual_topic: str | None
    last_manual_reason: str | None


def validate_extracted_metadata(raw: ExtractedMetadata | dict[str, Any]) -> ExtractedMetadata:
    """
    Normalize and validate the cross-module metadata contract.

    `extra` is explicitly *not* a place for fields that other modules depend on.
    If a future change needs a cross-module field, promote it into `ExtractedMetadata`.
    """
    metadata = dict(raw or {})
    extra = metadata.get("extra")
    if extra is None:
        extra = {}
    if not isinstance(extra, dict):
        raise TypeError("metadata.extra must be a dict when provided")

    overlap = sorted(set(extra.keys()) & METADATA_REQUIRED_KEYS)
    if overlap:
        raise ValueError(f"metadata.extra must not redefine contract keys: {', '.join(overlap)}")

    notes = metadata.get("notes") or []
    if not isinstance(notes, list):
        notes = [str(notes)]

    normalized: ExtractedMetadata = {
        "file_type": str(metadata.get("file_type") or "unknown"),
        "standard_date": str(metadata.get("standard_date") or ""),
        "extracted_text": str(metadata.get("extracted_text") or ""),
        "is_scanned": bool(metadata.get("is_scanned", False)),
        "preview_path": metadata.get("preview_path"),
        "ocr_error": metadata.get("ocr_error"),
        "notes": [str(item) for item in notes],
    }
    if extra:
        normalized["extra"] = extra
    return normalized
