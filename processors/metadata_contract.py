from __future__ import annotations

from contracts import (
    ExtractedMetadata,
    FileType,
    OCRStatus,
    VideoMetadata,
    validate_extracted_metadata,
)
from core_utils import FileUtils


def build_metadata_payload(
    *,
    file_type: FileType,
    standard_date: str | None,
    extracted_text: str,
    is_scanned: bool,
    preview_path: str | None,
    ocr_status: OCRStatus | None = None,
    ocr_error: str | None,
    notes: list[str],
    video: VideoMetadata | None = None,
) -> ExtractedMetadata:
    metadata: ExtractedMetadata = {
        "file_type": file_type,
        "standard_date": FileUtils.normalize_standard_date(standard_date),
        "extracted_text": extracted_text or "",
        "is_scanned": bool(is_scanned),
        "preview_path": preview_path,
        "ocr_status": ocr_status,
        "ocr_error": ocr_error,
        "notes": notes,
    }
    if video:
        metadata["video"] = video
    return validate_extracted_metadata(metadata)


def build_invalid_video_metadata(
    *,
    file_type: FileType,
    standard_date: str | None,
    extracted_text: str,
    is_scanned: bool,
    preview_path: str | None,
    ocr_status: OCRStatus | None = None,
    ocr_error: str | None,
    notes: list[str],
    video: VideoMetadata,
) -> ExtractedMetadata:
    return build_metadata_payload(
        file_type=file_type,
        standard_date=standard_date,
        extracted_text=extracted_text,
        is_scanned=is_scanned,
        preview_path=preview_path,
        ocr_status=ocr_status,
        ocr_error=ocr_error,
        notes=notes,
        video=video,
    )
