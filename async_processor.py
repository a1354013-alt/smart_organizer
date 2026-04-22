from __future__ import annotations

"""
非同步（多執行緒）處理與進度回饋模組。

此模組以 ThreadPoolExecutor 進行並行處理；不提供持久化的 job queue。
"""
import concurrent.futures
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence, TypeVar

TItem = TypeVar("TItem")
TResult = TypeVar("TResult")

@dataclass
class ProgressState:
    """進度狀態物件"""
    total: int = 0
    current: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)
    cancelled: bool = False
    
    def update(self, completed: int = 1):
        self.current += completed
    
    def add_error(self, filename: str, error: str):
        self.errors.append({"file": filename, "error": error})
    
    @property
    def percentage(self) -> float:
        if self.total == 0:
            return 0.0
        return min(100.0, (self.current / self.total) * 100.0)

class AsyncProcessor:
    """非同步處理器"""
    
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self._cancel_event = threading.Event()
    
    def cancel(self):
        """請求取消所有進行中的任務"""
        self._cancel_event.set()
    
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()
    
    def reset_cancel(self):
        """重置取消狀態"""
        self._cancel_event.clear()
    
    def process_batch(
        self,
        items: Sequence[TItem],
        process_fn: Callable[[TItem], TResult],
        progress_callback: Optional[Callable[[ProgressState], None]] = None,
        item_name: str = "項目"
    ) -> list[TResult]:
        """
        批量處理項目
        
        Args:
            items: 待處理項目列表
            process_fn: 處理函式 (item) -> result
            progress_callback: 進度回調函式 (ProgressState) -> None
            item_name: 項目名稱 (用於錯誤訊息)
        
        Returns:
            處理結果列表
        """
        self.reset_cancel()
        progress = ProgressState(total=len(items))
        results: list[TResult | None] = [None] * len(items)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_index = {executor.submit(process_fn, item): idx for idx, item in enumerate(items)}
            
            # 處理完成任務
            for future in concurrent.futures.as_completed(future_to_index):
                if self.is_cancelled():
                    progress.cancelled = True
                    break
                    
                idx = future_to_index[future]
                item = items[idx]
                try:
                    result = future.result()
                    results[idx] = result
                except Exception as e:
                    progress.add_error(getattr(item, "name", None) or str(item), str(e))
                    # 單項失敗不中斷整體流程
                finally:
                    progress.update()
                    if progress_callback:
                        progress_callback(progress)
        
        return [r for r in results if r is not None]

# 全域單例 (供 app.py 使用)
async_processor = AsyncProcessor(max_workers=4)
