from __future__ import annotations

import atexit
import importlib
from pathlib import Path
from typing import Any

import streamlit as st

from config import DB_PATH, PROJECT_ROOT, REPO_ROOT, UPLOAD_DIR
from core import FileProcessor
from frontend_safety import inject_browser_storage_sanitizer
from i18n import DEFAULT_LANGUAGE, t
from logging_config import setup_logging
from runtime_config import RuntimeConfig
from startup import initialize_startup
from storage import MAX_UPLOAD_BATCH_BYTES, MAX_UPLOAD_BYTES, StorageManager
from ui_common import UIContext, inject_global_css
from ui_execute import render_execute
from ui_home import render_home, render_sidebar
from ui_records import render_records
from ui_review import render_review
from ui_search import render_search
from ui_state import init_session_state
from ui_upload import render_upload

_REGISTERED_STORAGE_CLOSE_IDS: set[int] = set()
_BOOTSTRAPPED_STORAGES: dict[tuple[str, str, str], StorageManager] = {}


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


def _close_storage(storage: StorageManager) -> None:
    storage.close()
    _REGISTERED_STORAGE_CLOSE_IDS.discard(id(storage))


def _register_storage_close(storage: StorageManager) -> None:
    storage_id = id(storage)
    if storage_id in _REGISTERED_STORAGE_CLOSE_IDS:
        return
    atexit.register(_close_storage, storage)
    _REGISTERED_STORAGE_CLOSE_IDS.add(storage_id)


def clear_test_service_cache() -> None:
    for storage in list(_BOOTSTRAPPED_STORAGES.values()):
        _close_storage(storage)
    _BOOTSTRAPPED_STORAGES.clear()
    clear_cache = getattr(_bootstrap_services, "clear", None)
    if callable(clear_cache):
        clear_cache()


@st.cache_resource
def _bootstrap_services(
    db_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    upload_dir: str | Path | None = None,
) -> tuple[FileProcessor, StorageManager]:
    resolved_db_path = Path(db_path) if db_path is not None else DB_PATH
    resolved_repo_root = Path(repo_root) if repo_root is not None else REPO_ROOT
    resolved_upload_dir = Path(upload_dir) if upload_dir is not None else UPLOAD_DIR
    cache_key = (str(resolved_db_path), str(resolved_repo_root), str(resolved_upload_dir))
    storage: StorageManager | None = None
    try:
        processor = FileProcessor()
        storage = StorageManager(*cache_key)
        previous = _BOOTSTRAPPED_STORAGES.get(cache_key)
        if previous is not None and previous is not storage:
            _close_storage(previous)
        _BOOTSTRAPPED_STORAGES[cache_key] = storage
        _register_storage_close(storage)
        return processor, storage
    except Exception:
        if storage is not None:
            _close_storage(storage)
            _BOOTSTRAPPED_STORAGES.pop(cache_key, None)
        raise


def _build_context(runtime_config: RuntimeConfig | None = None) -> UIContext:
    db_path = runtime_config.db_path if runtime_config is not None else DB_PATH
    repo_root = runtime_config.repo_root if runtime_config is not None else REPO_ROOT
    upload_dir = runtime_config.upload_dir if runtime_config is not None else UPLOAD_DIR
    project_root = runtime_config.project_root if runtime_config is not None else PROJECT_ROOT
    if runtime_config is None:
        processor, storage = _bootstrap_services()
    else:
        processor, storage = _bootstrap_services(
            str(db_path),
            str(repo_root),
            str(upload_dir),
        )
    return UIContext(
        processor=processor,
        storage=storage,
        project_root=project_root,
        upload_dir=upload_dir,
        repo_root=repo_root,
        db_path=db_path,
        max_upload_bytes=MAX_UPLOAD_BYTES,
        max_upload_batch_bytes=MAX_UPLOAD_BATCH_BYTES,
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
    startup_state = initialize_startup(PROJECT_ROOT)
    _configure_page()
    context = _build_context(startup_state.config)
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
