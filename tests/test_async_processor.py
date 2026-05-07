from __future__ import annotations

import threading
import time

from async_processor import AsyncProcessor


def test_async_processor_cancel_skips_pending_items():
    processor = AsyncProcessor(max_workers=1)
    started = threading.Event()

    def work(item: int) -> int:
        if item == 0:
            started.set()
            time.sleep(0.2)
        return item

    def cancel_soon() -> None:
        started.wait(timeout=1.0)
        processor.cancel()

    thread = threading.Thread(target=cancel_soon)
    thread.start()
    try:
        result = processor.process_batch([0, 1, 2, 3], work)
    finally:
        thread.join(timeout=1.0)

    assert result.cancelled is True
    assert result.completed_count >= 1
    assert result.skipped_count >= 1
    assert result.failed_count == 0
    assert result.cancelled_count == 0
    assert 0 in result.results
    assert "COMPLETED" in result.item_statuses
    assert "SKIPPED" in result.item_statuses


def test_async_processor_tracks_failed_and_cancelled_items():
    processor = AsyncProcessor(max_workers=2)
    release = threading.Event()
    started = threading.Event()

    def work(item: int) -> int:
        if item in {0, 1}:
            started.set()
            release.wait(timeout=1.0)
        if item == 2:
            raise RuntimeError("boom")
        return item

    def cancel_soon() -> None:
        started.wait(timeout=1.0)
        processor.cancel()
        release.set()

    thread = threading.Thread(target=cancel_soon)
    thread.start()
    try:
        result = processor.process_batch([0, 1, 2, 3], work)
    finally:
        thread.join(timeout=1.0)

    assert result.cancelled is True
    assert result.completed_count >= 1
    assert result.skipped_count >= 1 or result.cancelled_count >= 1
    assert set(result.item_statuses).issubset({"PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "SKIPPED"})


def test_async_processor_tracks_failed_items_without_cancellation():
    processor = AsyncProcessor(max_workers=1)

    def work(item: int) -> int:
        if item == 1:
            raise RuntimeError("boom")
        return item

    result = processor.process_batch([0, 1, 2], work)

    assert result.cancelled is False
    assert result.completed_count == 2
    assert result.failed_count == 1
    assert result.item_statuses == ["COMPLETED", "FAILED", "COMPLETED"]
