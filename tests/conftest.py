# ruff: noqa: I001
import atexit
import gc
import os
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, cast

import pytest
from _pytest import pathlib as pytest_pathlib
from _pytest import tmpdir as pytest_tmpdir


# 讓 `pytest -q` 在專案根目錄可直接執行，不需手動設定 PYTHONPATH。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

from storage import StorageManager  # noqa: E402

# Keep pytest temp writes outside the repo so delivery cleanliness tests stay meaningful.
TEST_TMP = Path(tempfile.gettempdir()) / f"smart_organizer_tests_{uuid.uuid4().hex}"
TEST_TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = str(TEST_TMP)
os.environ["TEMP"] = str(TEST_TMP)
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(TEST_TMP)
os.environ["SMART_ORGANIZER_DATA_DIR"] = str(TEST_TMP / "runtime-data")
tempfile.tempdir = str(TEST_TMP)

_ORIG_CLEANUP_DEAD_SYMLINKS = pytest_pathlib.cleanup_dead_symlinks


def _safe_cleanup_dead_symlinks(root: Path) -> None:
    try:
        _ORIG_CLEANUP_DEAD_SYMLINKS(root)
    except PermissionError:
        return


pytest_pathlib.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks
pytest_tmpdir.cleanup_dead_symlinks = _safe_cleanup_dead_symlinks


def pytest_configure(config) -> None:
    config.option.basetemp = str(PROJECT_ROOT / f".pytest_runtime_tmp_{uuid.uuid4().hex}")


@atexit.register
def _cleanup_test_tmp() -> None:
    shutil.rmtree(TEST_TMP, ignore_errors=True)


def _cleanup_repo_caches() -> None:
    try:
        pycache_paths = list(PROJECT_ROOT.rglob("__pycache__"))
    except FileNotFoundError:
        pycache_paths = []
    for path in pycache_paths:
        with suppress(PermissionError, FileNotFoundError):
            shutil.rmtree(path, ignore_errors=True)
    for pattern in (".mypy_cache", ".ruff_cache", ".pytest_runtime_tmp*"):
        for path in PROJECT_ROOT.glob(pattern):
            with suppress(PermissionError):
                shutil.rmtree(path, ignore_errors=True)
    for path in (PROJECT_ROOT / "repo", PROJECT_ROOT / "uploads", TEST_TMP / "runtime-data"):
        with suppress(PermissionError):
            shutil.rmtree(path, ignore_errors=True)
    for path in (PROJECT_ROOT / "smart_organizer.db",):
        with suppress(FileNotFoundError, PermissionError):
            path.unlink()
    for pattern in ("*.pyc", "*.pyc.*"):
        try:
            compiled_paths = list(PROJECT_ROOT.rglob(pattern))
        except FileNotFoundError:
            compiled_paths = []
        for path in compiled_paths:
            with suppress(FileNotFoundError, PermissionError):
                path.unlink()


_cleanup_repo_caches()


def _retry(
    func,
    *args,
    attempts: int = 40,
    delay_seconds: float = 0.25,
    swallow_permission_error: bool = True,
    **kwargs,
):
    last_exc = None
    for _ in range(max(1, int(attempts))):
        try:
            return func(*args, **kwargs)
        except PermissionError as exc:
            last_exc = exc
            time.sleep(delay_seconds)

    if last_exc is not None and swallow_permission_error:
        # Avoid failing the whole test run due to transient file locks (e.g. AV scan).
        # This is a last resort; leaked temp files/dirs are confined to the repo tmp dir.
        return None

    if last_exc is not None:
        raise last_exc


# Some Windows environments temporarily lock newly created files/dirs (e.g. AV scan),
# causing tests to intermittently fail on cleanup. Patch common cleanup primitives
# to retry on PermissionError.
_ORIG_UNLINK = os.unlink
_ORIG_REMOVE = os.remove
_ORIG_RMTREE = shutil.rmtree


def _robust_unlink(path, *args, **kwargs):
    return _retry(_ORIG_UNLINK, path, *args, **kwargs)


def _robust_remove(path, *args, **kwargs):
    return _retry(_ORIG_REMOVE, path, *args, **kwargs)


def _robust_rmtree(path, *args, **kwargs):
    # Force ignore_errors via retry wrapper behavior as needed.
    return _retry(_ORIG_RMTREE, path, *args, **kwargs)


os.unlink = cast(Any, _robust_unlink)
os.remove = cast(Any, _robust_remove)
shutil.rmtree = cast(Any, _robust_rmtree)


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session, exitstatus):
    """Mitigate transient Windows PermissionError during pytest tmp cleanup.

    Some Windows setups briefly lock freshly-created temp dirs/files (e.g. AV scans),
    which can cause pytest's own tmpdir cleanup (dead symlink scan) to crash with
    PermissionError. We wait a short time for basetemp to become readable.
    """

    try:
        try:
            basetemp = session.config._tmp_path_factory.getbasetemp()
        except Exception:
            basetemp = None

        if basetemp is None:
            return

        deadline = time.time() + 8.0
        while time.time() < deadline:
            try:
                # Force a scandir/iterdir to verify accessibility.
                for _ in Path(basetemp).iterdir():
                    break
                return
            except PermissionError:
                time.sleep(0.25)
            except FileNotFoundError:
                return
    finally:
        _cleanup_repo_caches()


@pytest.fixture(autouse=True)
def _close_storage_managers(monkeypatch):
    created: list[StorageManager] = []
    original_init = StorageManager.__init__

    def tracked_init(self, db_path: str, repo_root: str, upload_dir: str):
        original_init(self, db_path, repo_root, upload_dir)
        created.append(self)

    monkeypatch.setattr(StorageManager, "__init__", tracked_init)
    try:
        yield
    finally:
        for storage in reversed(created):
            storage.close()


@pytest.fixture(autouse=True)
def _clear_project_service_cache():
    try:
        import app_main
    except Exception:
        yield
        gc.collect()
        return

    try:
        yield
    finally:
        with suppress(Exception):
            app_main.clear_test_service_cache()
        gc.collect()


@pytest.fixture
def tmp_path():
    path = TEST_TMP / f"case_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
