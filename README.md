# 📁 智慧檔案整理助理 (v2.7 Steel-Fortified)

這是一個基於 Python 的智慧檔案整理工具，能自動根據時間與內容對 PDF 與照片進行分類、命名與整理。

## 🌟 核心功能
- **智慧分類**：基於規則與 LLM 摘要，自動判斷檔案主題（發票、合約、截圖等）。
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

### v2.7 Steel-Fortified (鋼鐵堡壘版) - 2026-03-06
- **FTS 同步修復**：`update_file_metadata` 現在會同步更新 FTS 索引，並確保 `content` 欄位不會被洗空。
- **Crash-safe Finalize**：實作「MOVING → 原子搬移 → COMPLETED」三階段流程，並加入 **Recovery 補償機制**，確保搬檔失敗不遺留 ghost 狀態。
- **並發上傳保護**：採用 `.part` 檔案與原子化 `os.replace` 機制，徹底消除 Race Condition。
- **清理流程安全邊界**：強化 `cleanup_orphaned_uploads`，支援 PNG 預覽圖清理並嚴格限制刪除範圍。
- **Schema Cascade**：為 `file_tags` 加入 `ON DELETE CASCADE`，確保刪除檔案時關聯標籤一併清除。
- **OpenAI 可配置化**：支援 `OPENAI_MODEL` 環境變數配置，並加入 30 秒請求超時控制。
- **依賴版本鎖定**：`requirements.txt` 已鎖定主要版本號，提升部署穩定性。

### v2.6 Steel-Reinforced (鋼鐵加固版)
- **FTS5 rowid 綁定**：修復 FTS 更新問題，確保 `INSERT OR REPLACE` 能正確作用。
- **暫存檔名唯一化**：暫存檔加入 hash 前綴，避免同名檔案上傳時互相覆蓋。
- **併發衝突防護**：在 `create_temp_file` 加入補償邏輯，處理 hash collision 時的孤兒檔案。
- **冪等性 Finalize**：`finalize_organization` 可重複呼叫，不產生副作用。
- **遞迴安全清理**：`cleanup_orphaned_uploads` 現在能正確處理子目錄，並加入預覽圖 TTL 清理機制。
