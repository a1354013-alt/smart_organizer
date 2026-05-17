from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import streamlit as st

from storage import SearchContentError
from ui_common import UIContext, handle_ui_exception, safe_display_text

logger = logging.getLogger(__name__)


def resolve_download_path(storage: Any, final_path: object) -> tuple[Path | None, str | None]:
    if not final_path:
        return None, "Record has no organized file path."
    try:
        repo_root = Path(storage.repo_root).expanduser().resolve()
        candidate = Path(str(final_path)).expanduser().resolve()
    except Exception:
        return None, "Record contains an invalid file path."
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return None, "Record path is outside the repository and cannot be downloaded."
    if not candidate.is_file():
        return None, "The organized file is no longer available on disk."
    return candidate, None


def render_search(context: UIContext) -> None:
    st.header("Search records")
    caption = getattr(st, "caption", None)
    if callable(caption):
        caption("Advanced workflow: search uploaded-file records by filename, summary, tags, and snippets.")
    search_query = st.text_input(
        "Search filename or content",
        placeholder="invoice / screenshot / contract",
    )
    if not search_query:
        st.info("Enter a keyword to search previously analyzed and organized upload records.")
        return

    with st.spinner("Searching..."):
        try:
            results = context.storage.search_content(search_query)
            if not results:
                st.info("No matching records found.")
                return
            st.success(f"Found {len(results)} result(s).")
            for result in results:
                original_name = safe_display_text(result.get("original_name"))
                standard_date = safe_display_text(result.get("standard_date"))
                with st.expander(f"{original_name} ({standard_date})"):
                    st.write(f"**Topic**: {safe_display_text(result.get('main_topic'))}")
                    st.write(f"**Path**: {safe_display_text(result.get('final_path'))}")
                    if result.get("all_tags"):
                        st.write(f"**Tags**: {safe_display_text(result.get('all_tags'))}")
                    st.write(f"**Snippet**: ...{safe_display_text(result.get('snippet', ''))}...")
                    download_path, download_warning = resolve_download_path(context.storage, result.get("final_path"))
                    if download_path is not None:
                        with download_path.open("rb") as handle:
                            st.download_button(
                                "Download file",
                                handle,
                                file_name=os.path.basename(str(download_path)),
                                key=f"dl_{result['file_id']}",
                            )
                    elif result.get("final_path"):
                        st.warning(download_warning or "This file cannot be downloaded safely.")
        except SearchContentError:
            logger.exception("search_content failed")
            st.error("Search index failed. Try rebuilding records in the Records tab.")
        except Exception as exc:
            logger.exception("render_search failed")
            handle_ui_exception("Search failed.", exc)
