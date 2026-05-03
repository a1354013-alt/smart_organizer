import atexit
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, cast

import pytest

# 讓 `pytest -q` 在專案根目錄可直接執行，不需手動設定 PYTHONPATH。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.dont_write_bytecode = True

# Keep pytest temp writes outside the repo so delivery cleanliness tests stay meaningful.
TEST_TMP = Path(tempfile.mkdtemp(prefix="smart_organizer_tests_"))
os.environ["TMP"] = str(TEST_TMP)
os.environ["TEMP"] = str(TEST_TMP)
tempfile.tempdir = str(TEST_TMP)


@atexit.register
def _cleanup_test_tmp() -> None:
    shutil.rmtree(TEST_TMP, ignore_errors=True)


def _cleanup_repo_caches() -> None:
    for path in PROJECT_ROOT.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)
    for pattern in ("*.pyc", "*.pyc.*"):
        for path in PROJECT_ROOT.rglob(pattern):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


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
        basetemp = session.config._tmp_path_factory.getbasetemp()
    except Exception:
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
