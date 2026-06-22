from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core_utils import FileUtils


@dataclass(frozen=True, slots=True)
class UploadValidationError:
    code: str
    filename: str
    detail: str


@dataclass(frozen=True, slots=True)
class UploadValidationResult:
    total_bytes: int
    errors: list[UploadValidationError]


def validate_single_upload(
    filename: object,
    size_bytes: object,
    *,
    max_file_bytes: int,
) -> list[UploadValidationError]:
    safe_name = FileUtils.sanitize_filename(Path(str(filename or "")).name)
    ext = Path(safe_name).suffix.lower()
    try:
        size = int(str(size_bytes))
    except (TypeError, ValueError):
        size = 0

    errors: list[UploadValidationError] = []
    if not safe_name.strip():
        errors.append(UploadValidationError("missing_filename", "", "Filename is required."))
        return errors
    if ext not in FileUtils.ALLOWED_UPLOAD_EXTENSIONS:
        errors.append(
            UploadValidationError(
                "unsupported_extension",
                safe_name,
                f"Unsupported upload extension: {ext or 'unknown'}",
            )
        )
    if size <= 0:
        errors.append(UploadValidationError("empty_file", safe_name, "Uploaded file is empty."))
    if size > int(max_file_bytes):
        errors.append(
            UploadValidationError(
                "file_too_large",
                safe_name,
                (
                    f"{safe_name}: file size {size} bytes exceeds the per-file limit of "
                    f"{int(max_file_bytes)} bytes."
                ),
            )
        )
    return errors


def validate_upload_batch(
    files: list[tuple[object, object]],
    *,
    max_file_bytes: int,
    max_batch_bytes: int,
) -> UploadValidationResult:
    total_bytes = 0
    errors: list[UploadValidationError] = []
    for filename, size_bytes in files:
        try:
            size = int(str(size_bytes))
        except (TypeError, ValueError):
            size = 0
        total_bytes += max(0, size)
        errors.extend(
            validate_single_upload(
                filename,
                size,
                max_file_bytes=max_file_bytes,
            )
        )

    if total_bytes > int(max_batch_bytes):
        errors.append(
            UploadValidationError(
                "batch_too_large",
                "",
                (
                    f"Batch size {total_bytes} bytes exceeds the upload batch limit of "
                    f"{int(max_batch_bytes)} bytes."
                ),
            )
        )
    return UploadValidationResult(total_bytes=total_bytes, errors=errors)
