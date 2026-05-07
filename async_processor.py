from __future__ import annotations

import concurrent.futures
import threading
from dataclasses import dataclass, field
from typing import Callable, Generic, Optional, Sequence, TypeVar

TItem = TypeVar("TItem")
TResult = TypeVar("TResult")


@dataclass
class ProgressState:
    total: int = 0
    current: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    cancelled: bool = False
    skipped_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    cancelled_count: int = 0

    def update(self, completed: int = 1) -> None:
        self.current += completed

    def add_error(self, filename: str, error: str) -> None:
        self.errors.append({"file": filename, "error": error})

    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0.0
        return min(100.0, (self.current / self.total) * 100.0)


@dataclass
class BatchProcessResult(Generic[TResult]):
    results: list[TResult]
    cancelled: bool
    skipped_count: int
    completed_count: int
    failed_count: int
    cancelled_count: int
    item_statuses: list[str]


class AsyncProcessor:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def reset_cancel(self) -> None:
        self._cancel_event.clear()

    def process_batch(
        self,
        items: Sequence[TItem],
        process_fn: Callable[[TItem], TResult],
        progress_callback: Optional[Callable[[ProgressState], None]] = None,
        item_name: str = "item",
    ) -> BatchProcessResult[TResult]:
        self.reset_cancel()
        progress = ProgressState(total=len(items))
        results: list[TResult | None] = [None] * len(items)
        item_statuses: list[str] = ["PENDING"] * len(items)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_index: dict[concurrent.futures.Future[TResult], int] = {}
            next_index = 0

            def submit_until_full() -> None:
                nonlocal next_index
                while next_index < len(items) and len(future_to_index) < max(1, self.max_workers) and not self.is_cancelled():
                    future = executor.submit(process_fn, items[next_index])
                    future_to_index[future] = next_index
                    item_statuses[next_index] = "RUNNING"
                    next_index += 1

            submit_until_full()

            while future_to_index:
                done, _pending = concurrent.futures.wait(
                    future_to_index,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )

                for future in done:
                    idx = future_to_index.pop(future)
                    item = items[idx]

                    try:
                        results[idx] = future.result()
                        progress.completed_count += 1
                        item_statuses[idx] = "COMPLETED"
                    except concurrent.futures.CancelledError:
                        progress.cancelled_count += 1
                        item_statuses[idx] = "CANCELLED"
                    except Exception as exc:
                        progress.failed_count += 1
                        item_statuses[idx] = "FAILED"
                        progress.add_error(getattr(item, "name", None) or f"{item_name}:{item}", str(exc))
                    finally:
                        if self.is_cancelled():
                            progress.cancelled = True
                        progress.update()
                        if progress_callback:
                            progress_callback(progress)

                if self.is_cancelled():
                    progress.cancelled = True
                    for future, idx in list(future_to_index.items()):
                        if future.cancel():
                            progress.cancelled_count += 1
                            item_statuses[idx] = "CANCELLED"
                            progress.update()
                            future_to_index.pop(future, None)
                            if progress_callback:
                                progress_callback(progress)
                    remaining = len(items) - next_index
                    if remaining > 0:
                        progress.skipped_count += remaining
                        progress.current += remaining
                        for idx in range(next_index, len(items)):
                            item_statuses[idx] = "SKIPPED"
                    break

                submit_until_full()

        return BatchProcessResult(
            results=[result for result in results if result is not None],
            cancelled=progress.cancelled,
            skipped_count=progress.skipped_count,
            completed_count=progress.completed_count,
            failed_count=progress.failed_count,
            cancelled_count=progress.cancelled_count,
            item_statuses=item_statuses,
        )


async_processor = AsyncProcessor(max_workers=4)
