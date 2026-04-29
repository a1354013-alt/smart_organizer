import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import pytest

# 讓 `pytest -q` 在專案根目錄可直接執行，不需手動設定 PYTHONPATH。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure temp directories are writable/cleanable inside the repo.
# Some Windows environments can cause PermissionError for paths under the
# default %TEMP%, which breaks tests that rely on tempfile / sqlite.
REPO_TMP = PROJECT_ROOT / "tmp_test_write"
REPO_TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = str(REPO_TMP)
os.environ["TEMP"] = str(REPO_TMP)
tempfile.tempdir = str(REPO_TMP)


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


os.unlink = _robust_unlink  # type: ignore[assignment]
os.remove = _robust_remove  # type: ignore[assignment]
shutil.rmtree = _robust_rmtree  # type: ignore[assignment]


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

