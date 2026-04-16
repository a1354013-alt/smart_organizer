"""
非同步處理與進度回饋模組
提供耗時任務的非同步執行、進度追蹤與優雅取消機制
"""
import concurrent.futures
import threading
from typing import Callable, Any, List, Optional, Dict
from dataclasses import dataclass, field

@dataclass
class ProgressState:
    """進度狀態物件"""
    total: int = 0
    current: int = 0
    errors: List[Dict[str, str]] = field(default_factory=list)
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
        items: List[Any],
        process_fn: Callable[[Any], Any],
        progress_callback: Optional[Callable[[ProgressState], None]] = None,
        item_name: str = "項目"
    ) -> List[Any]:
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
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 提交所有任務
            future_to_item = {
                executor.submit(process_fn, item): item 
                for item in items
            }
            
            # 處理完成任務
            for future in concurrent.futures.as_completed(future_to_item):
                if self.is_cancelled():
                    break
                    
                item = future_to_item[future]
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    progress.add_error(str(item), str(e))
                    # 單項失敗不中斷整體流程
                finally:
                    progress.update()
                    if progress_callback:
                        progress_callback(progress)
        
        return results

# 全域單例 (供 app.py 使用)
async_processor = AsyncProcessor(max_workers=4)
