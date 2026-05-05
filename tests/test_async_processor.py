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
    assert 0 in result.results
