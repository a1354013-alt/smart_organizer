# 📁 智慧檔案整理助理 (v2.7.4 Steel-Fortified Final Ultimate)

這是一個基於 Python 的智慧檔案整理工具，能自動根據時間與內容對 PDF 與照片進行分類、命名與整理。

## 🌟 核心功能
- **智慧分類**：系統主要透過**規則引擎**進行主題分類（發票、合約、截圖等），並可選擇使用 **LLM 生成文件摘要與輔助標籤**。
- **視覺化預覽**：支援照片縮圖與 PDF 第一頁自動轉圖預覽。
- **全文檢索**：內建 SQLite FTS5，支援對檔案內容進行秒級關鍵字搜尋。
- **掃描檔補強**：自動偵測掃描 PDF 並進行「抽樣頁數」OCR（預設最多 3 頁，可用 `PDF_OCR_MAX_PAGES` 調整），提升可搜尋性。
- **架構加固**：路徑操作完全封裝於 Storage 層，資料庫驅動的檔案生命週期管理。

## 🛠️ 安裝說明

### 1. 系統級依賴 (OS Dependencies)
本專案需要以下系統工具支援 PDF 處理與 OCR：

> 重要：本專案已做「缺少依賴時的功能降級」：
> - 缺少 poppler（`pdftoppm`/`pdftocairo`）時：PDF 預覽會跳過，但其餘流程仍可運作。
> - 缺少 tesseract 或語言包時：OCR 會停用/跳過，仍可整理與搜尋（若 PDF 本身可抽到文字）。

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-chi-tra
```

**macOS (Homebrew):**
```bash
brew install poppler tesseract tesseract-lang
```

**Windows:**
- 安裝 Poppler（提供 `pdftoppm`）：確保 `pdftoppm.exe` 在 PATH 內，或設定環境變數 `POPPLER_PATH` 指向 Poppler 的 `bin` 目錄。
- 安裝 Tesseract（提供 `tesseract.exe`）：確保 `tesseract.exe` 在 PATH 內，並安裝繁中語言包（常見名稱 `chi_tra`）。

### 2. Python 環境設定
建議使用虛擬環境：
```bash
pip install -r requirements.txt
```

> 重要：`streamlit` 是 **App 啟動必要依賴**。若缺少 `streamlit`，App 無法啟動；但 OCR/PDF 預覽等「附加功能」可在缺少系統依賴時自動降級跳過。

### 3. （可選）開發與測試依賴
```bash
pip install -r requirements-dev.txt
pytest -q
```
> 提示：本專案已在 `tests/conftest.py` 補上測試路徑處理，直接在專案根目錄執行 `pytest -q` 不需要額外設定 `PYTHONPATH`。

## 📦 Release 交付包（正式包不附 tests）
- 使用 `create_release_zip.ps1` 產生的 **正式 release zip** 是「展示/執行用」最小包，**不包含 `tests/`**（避免交付包定位模糊）。
- 若需要驗證測試，請使用 source repo 執行 `pytest -q`。
- 請勿直接把整個工作目錄壓縮上傳（workspace 快照可能包含 `.git/`、`__pycache__/`、`.db`、暫存檔等殘留）。正式交付以 release zip 為準。
 - 正式 release zip 是 **runtime/demo package**，不是 source-development package。

## 🧯 整理失敗與重試（last_error）
- 若「執行整理」失敗，系統會把錯誤摘要寫入資料庫欄位 `last_error`，並在「查看紀錄」表格中顯示，方便診斷。
- 多數情況可直接重試：修正檔案權限/路徑、補齊系統依賴（如 poppler/tesseract）後再執行整理。
- 若檔案已遺失（暫存檔不存在），需要重新上傳或先用「重新整理檔案位置」檢查紀錄。

## 🔎 全文檢索（重要規格）
- `search_content()` 會先將輸入做 FTS 安全轉義；若轉義後變成空字串（例如只輸入括號、引號等特殊符號），會直接回傳空結果 `[]`（不走 metadata fallback），以避免 SQLite FTS5 例外並維持行為可預期。

## 🚀 執行方式
在專案根目錄執行：
```bash
streamlit run app.py
```

## 🔐 AI 摘要（安全開關）
- UI 預設 **不啟用** AI 摘要（不送出任何內容）。
- 需要時請在側邊欄手動開啟「啟用 AI 摘要」，並在環境中設定 `OPENAI_API_KEY`。

## ⚙️ 重要環境變數
- `OPENAI_API_KEY`: 啟用 AI 摘要所需
- `OPENAI_MODEL`: 預設 `gpt-4.1-mini`
- `OPENAI_TIMEOUT_SECONDS`: 預設 30
- `OPENAI_MAX_CHARS`: 送出摘要的文字最大字元數（預設 6000，會自動截斷）
- `POPPLER_PATH`: （Windows 常用）Poppler `bin` 路徑
- `PDF_TEXT_MAX_PAGES`: PDF 文字抽取頁數上限（預設 10）
- `PDF_OCR_MAX_PAGES`: PDF OCR 抽樣頁數上限（預設 3，上限 5）
- `MAX_HEAVY_PROCESS_MB`: OCR/預覽等「耗時處理」的檔案大小上限（預設 15MB，避免卡死 UI）

## 📂 專案結構
- `app.py`: Streamlit UI 介面，負責流程調度。
- `core.py`: 核心處理模組，包含 OCR、PDF 處理與 AI 邏輯。
- `storage.py`: 資料庫與檔案管理層，負責路徑封裝與 FTS5 搜尋。
- `uploads/`: 暫存上傳檔案。
- `repo/`: 整理後的檔案儲存庫。
- `smart_organizer.db`: SQLite 資料庫。

## 📜 更新日誌 (Changelog)

### v2.7.4 Steel-Fortified Final Ultimate - 2026-03-14
- **狀態機收斂補強**：優化 `_recover_moving_file` 邏輯，加入「雙失蹤」異常處理，確保在極端情況下狀態能自動回退而不卡死。
- **FTS 查詢防禦**：在 `search_content` 中加入空查詢與特殊字元過濾，提升全文檢索的魯棒性。
- **極致乾淨打包**：優化發佈流程，徹底排除所有測試目錄、資料庫殘留與開發暫存檔。
- **代碼精煉**：移除 `app.py` 中未使用的引用，保持專案結構俐落。

### v2.7.3 Steel-Fortified Final Refined - 2026-03-14
- **併發清理補強**：在 `create_temp_file` 中加入併發重複上傳的即時清理邏輯，防止 `uploads/` 目錄產生孤兒暫存檔。
- **清理年齡保護**：`cleanup_orphaned_uploads` 引入 5 分鐘年齡保護機制，避免清理程序誤刪正在處理中的檔案。
- **狀態機重構**：重構 `finalize_organization` 流程，將 Recovery 邏輯獨立化並統一連線管理，提升系統穩定性。
- **文檔措辭校正**：修正 README 描述，以更嚴謹的工程措辭描述併發安全與分類邏輯。

### v2.7.2 Steel-Fortified Final - 2026-03-14
- **強化併發防護**：`create_temp_file` 改為「先查後寫」並搭配 `BEGIN IMMEDIATE` 交易鎖定，顯著降低併發衝突風險。
- **收窄清理安全邊界**：`cleanup_orphaned_uploads` 加入正則表達式檢查，僅清理符合規則的暫存檔，排除日誌或鎖定檔。
- **FTS 註解校正**：修正 `core.py` 中關於 FTS5 轉義邏輯的描述。
- **文檔 Typo 修正**：修正 README 中「掃描檔補強」的文字錯誤。

### v2.7.1 Steel-Fortified Hotfix - 2026-03-14
- **缺失依賴補全**：在 `requirements.txt` 中新增 `matplotlib`，修復部署時的 `ModuleNotFoundError`。
- **強化 Crash Recovery**：優化 `finalize_organization` 恢復邏輯，增加對 `temp_path` 存在性的檢查，避免在不完整搬移時誤標記為 `COMPLETED`。
- **預覽圖清理安全性**：確保 `cleanup_orphaned_uploads` 檔名解析使用 `Path(name).stem`，避免檔名中含 `.png` 等字串時被誤解析。
- **文檔描述校正**：修正 README 中關於分類邏輯的描述，與實際程式碼行為對齊。

### v2.7 Steel-Fortified (鋼鐵堡壘版) - 2026-03-06
- **FTS 同步修復**：`update_file_metadata` 現在會同步更新 FTS 索引，並確保 `content` 欄位不會被洗空。
- **Crash-safe Finalize**：實作「MOVING → 原子搬移 → COMPLETED」三階段流程，並加入 **Recovery 補償機制**，確保搬檔失敗不遺留 ghost 狀態。
- **並發上傳保護**：採用 `.part` 檔案與原子化 `os.replace` 機制，徹底消除 Race Condition。
- **清理流程安全邊界**：強化 `cleanup_orphaned_uploads`，支援 PNG 預覽圖清理並嚴格限制刪除範圍。
- **Schema Cascade**：為 `file_tags` 加入 `ON DELETE CASCADE`，確保刪除檔案時關聯標籤一併清除。
- **OpenAI 可配置化**：支援 `OPENAI_MODEL` 環境變數配置，並加入 30 秒請求超時控制。
- **依賴版本鎖定**：`requirements.txt` 已鎖定主要版本號，提升部署穩定性。
