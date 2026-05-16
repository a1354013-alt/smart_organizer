from __future__ import annotations

import atexit
import importlib
from typing import Any

import streamlit as st

from config import DB_PATH, PROJECT_ROOT, REPO_ROOT, UPLOAD_DIR
from core import FileProcessor
from frontend_safety import inject_browser_storage_sanitizer
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
from version import APP_NAME

_REGISTERED_STORAGE_CLOSE_IDS: set[int] = set()


def _optional_import(module_name: str) -> Any:
    try:
        module = importlib.import_module(module_name)
    except Exception:  # pragma: no cover
        return None
    return module


def _configure_page() -> None:
    st.set_page_config(page_title=APP_NAME, layout="wide")
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


def main() -> None:
    _configure_page()
    context = _build_context()
    inject_global_css()
    init_session_state()
    render_sidebar(context)
    render_home(context)

    tab_upload, tab_review, tab_execute, tab_search, tab_records = st.tabs(
        [
            "Advanced Upload",
            "Review Uploads",
            "Execute Upload Organizer",
            "Search Records",
            "Records",
        ]
    )
    with tab_upload:
        render_upload(context)
    with tab_review:
        render_review(context)
    with tab_execute:
        render_execute(context)
    with tab_search:
        render_search(context)
    with tab_records:
        render_records(context)


if __name__ == "__main__":
    main()
