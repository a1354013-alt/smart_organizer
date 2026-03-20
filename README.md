# 📁 智慧檔案整理助理 (v2.7.4 Steel-Fortified Final Ultimate)

這是一個基於 Python 的智慧檔案整理工具，能自動根據時間與內容對 PDF 與照片進行分類、命名與整理。

## 🌟 核心功能
- **智慧分類**：系統主要透過**規則引擎**進行主題分類（發票、合約、截圖等），並可選擇使用 **LLM 生成文件摘要與輔助標籤**。
- **視覺化預覽**：支援照片縮圖與 PDF 第一頁自動轉圖預覽。
- **全文檢索**：內建 SQLite FTS5，支援對檔案內容進行秒級關鍵字搜尋。
- **掃描檔補強**：自動偵測掃描 PDF 並執行第一頁 OCR，確保可搜尋性。
- **架構加固**：路徑操作完全封裝於 Storage 層，資料庫驅動的檔案生命週期管理。

## 🛠️ 安裝說明

### 1. 系統級依賴 (OS Dependencies)
本專案需要以下系統工具支援 PDF 處理與 OCR：

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-chi-tra
```

**macOS (Homebrew):**
```bash
brew install poppler tesseract tesseract-lang
```

### 2. Python 環境設定
建議使用虛擬環境：
```bash
pip install -r requirements.txt
```

## 🚀 執行方式
在專案根目錄執行：
```bash
streamlit run app.py
```

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
