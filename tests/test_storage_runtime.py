from __future__ import annotations

import atexit

from app_main import _bootstrap_services
from storage import StorageManager


def test_storage_close_is_idempotent_and_blocks_reuse():
    storage = StorageManager(":memory:", ":memory:", ":memory:")
    storage.close()
    storage.close()

    try:
        storage._get_connection()
    except RuntimeError as exc:
        assert "closed" in str(exc).lower()
    else:
        raise AssertionError("Expected closed storage to reject new connections")


def test_bootstrap_registers_storage_close_once(monkeypatch):
    registrations: list[object] = []
    monkeypatch.setattr(atexit, "register", lambda func: registrations.append(func))
    _bootstrap_services.clear()

    _bootstrap_services()
    _bootstrap_services()

    assert len(registrations) == 1
