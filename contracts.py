from __future__ import annotations

from typing import Any, NotRequired, TypedDict


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

    # Optional extras (may be extended, but should remain backward compatible)
    extra: NotRequired[dict[str, Any]]


class DecisionHistory(TypedDict, total=False):
    decision_source: str  # e.g. "RULE", "MANUAL_OVERRIDE", "RULE_RECLASSIFY", "RECOVERY"
    decision_updated_at: str
    last_manual_topic: str | None
    last_manual_reason: str | None

