from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import streamlit as st

from i18n import t
from storage import SearchContentError
from ui_common import UIContext, handle_ui_exception, safe_display_text

logger = logging.getLogger(__name__)


def resolve_download_path(storage: Any, final_path: object) -> tuple[Path | None, str | None]:
    if not final_path:
        return None, t("search_records.no_final_path")
    try:
        repo_root = Path(storage.repo_root).expanduser().resolve()
        candidate = Path(str(final_path)).expanduser().resolve()
    except Exception:
        return None, t("search_records.invalid_path")
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return None, t("search_records.path_outside_repo")
    if not candidate.is_file():
        return None, t("search_records.file_missing")
    return candidate, None


def render_search(context: UIContext, *, show_header: bool = True) -> None:
    if show_header:
        st.header(t("search_records.search_title"))
    search_query = st.text_input(
        t("search_records.search_input_label"),
        placeholder=t("search_records.search_input_placeholder"),
    )
    if not search_query:
        st.info(t("search_records.search_empty"))
        return

    with st.spinner(t("search_records.searching")):
        try:
            results = context.storage.search_content(search_query)
            if not results:
                st.info(t("search_records.search_no_results"))
                return
            st.success(t("search_records.search_found", count=len(results)))
            for result in results:
                original_name = safe_display_text(result.get("original_name"))
                standard_date = safe_display_text(result.get("standard_date"))
                with st.expander(f"{original_name} ({standard_date})"):
                    st.write(f"**{t('search_records.topic')}**: {safe_display_text(result.get('main_topic'))}")
                    st.write(f"**{t('search_records.path')}**: {safe_display_text(result.get('final_path'))}")
                    if result.get("all_tags"):
                        st.write(f"**{t('search_records.tags')}**: {safe_display_text(result.get('all_tags'))}")
                    st.write(f"**{t('search_records.snippet')}**: ...{safe_display_text(result.get('snippet', ''))}...")
                    download_path, download_warning = resolve_download_path(context.storage, result.get("final_path"))
                    if download_path is not None:
                        with download_path.open("rb") as handle:
                            st.download_button(
                                t("search_records.download"),
                                handle,
                                file_name=os.path.basename(str(download_path)),
                                key=f"dl_{result['file_id']}",
                            )
                    elif result.get("final_path"):
                        st.warning(download_warning or t("search_records.download_unavailable"))
        except SearchContentError:
            logger.exception("search_content failed")
            st.error(t("search_records.search_index_failed"))
        except Exception as exc:
            logger.exception("render_search failed")
            handle_ui_exception(t("search_records.search_failed"), exc)
