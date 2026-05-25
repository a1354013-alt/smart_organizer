from __future__ import annotations

import atexit
import importlib
from typing import Any

import streamlit as st

from config import DB_PATH, PROJECT_ROOT, REPO_ROOT, UPLOAD_DIR
from core import FileProcessor
from frontend_safety import inject_browser_storage_sanitizer
from i18n import DEFAULT_LANGUAGE, t
from logging_config import setup_logging
from storage import MAX_UPLOAD_BYTES, StorageManager
from ui_common import UIContext, inject_global_css
from ui_execute import render_execute
from ui_home import render_home, render_sidebar
from ui_records import render_records
from ui_review import render_review
from ui_search import render_search
from ui_state import init_session_state
from ui_upload import render_upload

_REGISTERED_STORAGE_CLOSE_IDS: set[int] = set()


def _optional_import(module_name: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except Exception:  # pragma: no cover
        return None
    return module


def _configure_page() -> None:
    st.set_page_config(page_title=t("app.page_title", lang=DEFAULT_LANGUAGE), layout="wide")
    inject_browser_storage_sanitizer(enabled=True)
    setup_logging()


def _register_storage_close(storage: StorageManager) -> None:
    storage_id = id(storage)
    if storage_id in _REGISTERED_STORAGE_CLOSE_IDS:
        return
    atexit.register(storage.close)
    _REGISTERED_STORAGE_CLOSE_IDS.add(storage_id)


@st.cache_resource
def _bootstrap_services() -> tuple[FileProcessor, StorageManager]:
    processor = FileProcessor()
    storage = StorageManager(str(DB_PATH), str(REPO_ROOT), str(UPLOAD_DIR))
    _register_storage_close(storage)
    return processor, storage


def _build_context() -> UIContext:
    processor, storage = _bootstrap_services()
    return UIContext(
        processor=processor,
        storage=storage,
        project_root=PROJECT_ROOT,
        upload_dir=UPLOAD_DIR,
        repo_root=REPO_ROOT,
        db_path=DB_PATH,
        max_upload_bytes=MAX_UPLOAD_BYTES,
        pandas=_optional_import("pandas"),
        plt=_optional_import("matplotlib.pyplot"),
    )


def get_main_tab_labels() -> list[str]:
    return [
        t("app.tabs.folder_scan"),
        t("app.tabs.upload_analysis"),
        t("app.tabs.review_results"),
        t("app.tabs.execute_organization"),
        t("app.tabs.search_records"),
    ]


def main() -> None:
    _configure_page()
    context = _build_context()
    inject_global_css()
    init_session_state()
    render_sidebar(context)

    tab_folder_scan, tab_upload, tab_review, tab_execute, tab_search_records = st.tabs(get_main_tab_labels())
    with tab_folder_scan:
        render_home(context)
    with tab_upload:
        render_upload(context)
    with tab_review:
        render_review(context)
    with tab_execute:
        render_execute(context)
    with tab_search_records:
        st.header(t("search_records.title"))
        st.markdown(t("search_records.description"))
        render_search(context, show_header=False)
        st.divider()
        render_records(context, show_header=False)


if __name__ == "__main__":
    main()
