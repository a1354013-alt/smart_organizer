import sys
from pathlib import Path

# 讓 `pytest -q` 在專案根目錄可直接執行，不需手動設定 PYTHONPATH。
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

