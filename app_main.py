from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from frontend_safety import inject_browser_storage_sanitizer
from logging_config import setup_logging
from storage import MAX_UPLOAD_BYTES, StorageManager
from version import APP_NAME
from core import FileProcessor
from ui_common import UIContext, inject_global_css
from ui_execute import render_execute
from ui_home import render_home, render_sidebar
from ui_records import render_records
from ui_review import render_review
from ui_search import render_search
from ui_state import init_session_state
from ui_upload import render_upload

st.set_page_config(page_title=APP_NAME, layout="wide")
inject_browser_storage_sanitizer(enabled=True)

pd: Any = None
try:
    import pandas as _pd

    pd = _pd
except Exception:  # pragma: no cover
    pass

plt: Any = None
try:
    import matplotlib.pyplot as _plt

    plt = _plt
except Exception:  # pragma: no cover
    pass

PROJECT_ROOT = Path(__file__).parent
UPLOAD_DIR = PROJECT_ROOT / "uploads"
REPO_ROOT = PROJECT_ROOT / "repo"
DB_PATH = PROJECT_ROOT / "smart_organizer.db"

setup_logging()


@st.cache_resource
def _bootstrap_services() -> tuple[FileProcessor, StorageManager]:
    processor = FileProcessor()
    storage = StorageManager(str(DB_PATH), str(REPO_ROOT), str(UPLOAD_DIR))
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
        pandas=pd,
        plt=plt,
    )


def main() -> None:
    context = _build_context()
    inject_global_css()
    init_session_state()
    render_sidebar(context)
    render_home(context)

    tab_upload, tab_review, tab_execute, tab_search, tab_records = st.tabs(
        ["上傳分析", "預覽確認", "執行整理", "搜尋", "整理紀錄"]
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


main()
