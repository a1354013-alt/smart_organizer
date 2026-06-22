from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import streamlit as st

from core_utils import FileUtils
from i18n import t
from services import UploadedFileData, analyze_upload_batch
from storage import MAX_UPLOAD_BATCH_BYTES, MAX_UPLOAD_BYTES
from supported_formats import SUPPORTED_UPLOAD_EXTENSIONS, supported_upload_extensions_label
from ui_common import (
    UIContext,
    build_uploaded_file_batch,
    format_bytes,
    handle_ui_exception,
    safe_display_text,
)
from ui_state import reset_review_state
from upload_validation import validate_upload_batch

logger = logging.getLogger(__name__)


def get_supported_upload_types() -> list[str]:
    return list(SUPPORTED_UPLOAD_EXTENSIONS)


def get_supported_upload_caption() -> str:
    return supported_upload_extensions_label()


def _uploaded_file_size(uploaded_file: Any) -> int:
    size = getattr(uploaded_file, "size", None)
    if isinstance(size, int) and size >= 0:
        return size
    try:
        return len(uploaded_file.getbuffer())
    except Exception:
        return 0


def validate_upload_batch_limits(
    uploaded_files: list[Any],
    *,
    max_file_bytes: int,
    max_batch_bytes: int,
) -> list[str]:
    display_by_safe_name = {
        FileUtils.sanitize_filename(Path(str(getattr(uploaded_file, "name", "uploaded file"))).name): safe_display_text(
            getattr(uploaded_file, "name", "uploaded file")
        )
        for uploaded_file in uploaded_files
    }
    size_by_safe_name = {
        FileUtils.sanitize_filename(Path(str(getattr(uploaded_file, "name", "uploaded file"))).name): _uploaded_file_size(uploaded_file)
        for uploaded_file in uploaded_files
    }
    validation = validate_upload_batch(
        [(getattr(uploaded_file, "name", "uploaded file"), _uploaded_file_size(uploaded_file)) for uploaded_file in uploaded_files],
        max_file_bytes=max_file_bytes,
        max_batch_bytes=max_batch_bytes,
    )
    errors: list[str] = []
    for error in validation.errors:
        if error.code == "file_too_large":
            errors.append(
                t(
                    "upload.limit_file",
                    name=display_by_safe_name.get(error.filename, safe_display_text(error.filename)),
                    size=format_bytes(size_by_safe_name.get(error.filename, 0)),
                    max_size=format_bytes(max_file_bytes),
                )
            )
        elif error.code == "batch_too_large":
            errors.append(t("upload.limit_batch", size=format_bytes(validation.total_bytes), max_size=format_bytes(max_batch_bytes)))
    return errors


def resolve_upload_limits(context: UIContext) -> tuple[int, int]:
    max_file_bytes = int(getattr(context, "max_upload_bytes", MAX_UPLOAD_BYTES))
    max_batch_bytes = int(getattr(context, "max_upload_batch_bytes", MAX_UPLOAD_BATCH_BYTES))
    return max_file_bytes, max(max_file_bytes, max_batch_bytes)


def render_upload(context: UIContext) -> None:
    st.header(t("upload.title"))
    st.markdown(t("upload.description"))
    st.caption(t("upload.supported_formats", formats=get_supported_upload_caption()))

    max_upload_bytes, batch_limit_bytes = resolve_upload_limits(context)
    st.caption(
        t(
            "upload.limit_summary",
            file_size=format_bytes(max_upload_bytes),
            batch_size=format_bytes(batch_limit_bytes),
        )
    )
    st.caption(t("upload.batch_guidance", size=format_bytes(batch_limit_bytes)))

    uploaded_files = st.file_uploader(
        t("upload.uploader_label"),
        type=get_supported_upload_types(),
        accept_multiple_files=True,
    )
    if not uploaded_files:
        st.info(t("upload.empty"))
        return

    uploaded_list = list(uploaded_files)
    limit_errors = validate_upload_batch_limits(
        uploaded_list,
        max_file_bytes=max_upload_bytes,
        max_batch_bytes=int(batch_limit_bytes),
    )
    if limit_errors:
        for error in limit_errors:
            st.error(safe_display_text(error))
        return

    total_size = sum(_uploaded_file_size(uploaded_file) for uploaded_file in uploaded_list)
    st.success(t("upload.ready", count=len(uploaded_list), size=format_bytes(total_size)))
    if total_size > max_upload_bytes:
        st.warning(t("upload.large_batch_warning"))
    if not st.button(t("upload.start_button"), key="analyze_button"):
        return

    reset_review_state()
    progress_bar = st.progress(0)
    status_text = st.empty()
    uploaded_batch = build_uploaded_file_batch(uploaded_list)

    def on_progress(index: int, total: int, uploaded: UploadedFileData) -> None:
        progress_bar.progress(index / total)
        safe_name = safe_display_text(uploaded.name)
        status_text.text(t("upload.progress", index=index, total=total, name=safe_name))
        st.session_state.current_processing_file = uploaded.name

    try:
        outcome = analyze_upload_batch(
            uploaded_batch,
            processor=context.processor,
            storage=context.storage,
            processing_options=st.session_state.get("processing_options"),
            progress_callback=on_progress,
        )
        progress_bar.progress(1.0)
        status_text.text(t("upload.complete"))
        st.session_state.analysis_results = outcome.results

        for error in outcome.errors:
            st.error(safe_display_text(error))
        if outcome.duplicates:
            st.warning(t("upload.duplicates_skipped", count=len(outcome.duplicates)))
            for duplicate in outcome.duplicates:
                st.info(safe_display_text(duplicate.display))
        if outcome.results:
            st.success(t("upload.continue_to_review", count=len(outcome.results)))
        else:
            st.warning(t("upload.no_results"))
    except Exception as exc:
        logger.exception("render_upload failed")
        handle_ui_exception(t("upload.failed"), exc)
