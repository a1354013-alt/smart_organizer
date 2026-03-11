# 智慧檔案整理助理 (Smart File Organizer)

這是一個基於 Python 的智慧檔案整理助理，能自動提取檔案時間、判斷主題，並將檔案整理成結構化的資料夾。

## 🚀 核心功能
- **自動時間提取**：優先使用照片 EXIF 資訊，備援使用檔案修改時間。
- **智慧主題分類**：基於 Rule-based 規則打分，自動識別發票、合約、報價單、截圖等主題。
- **結構化整理**：自動建立 `年份/月份` 資料夾，並以 `YYYY-MM-DD_主題_原始檔名` 重新命名。
- **資料庫管理**：使用 SQLite 紀錄所有處理歷史，支援快速搜尋與統計。
- **視覺化介面**：使用 Streamlit 提供直覺的上傳、預覽與統計功能。

## 📁 專案結構
- `app.py`: Streamlit UI 主程式。
- `core.py`: 核心處理邏輯 (時間提取、文字提取、分類器)。
- `storage.py`: 資料庫管理與檔案整理邏輯。
- `repo/`: 整理後的檔案儲存庫。
- `uploads/`: 檔案上傳暫存區。
- `smart_organizer.db`: SQLite 資料庫檔案。

## 🛠️ 安裝與執行
1. 安裝依賴套件：
   ```bash
   pip install streamlit pypdf Pillow exifread pandas reportlab
   ```
2. 執行應用程式：
   ```bash
   streamlit run app.py
   ```

## 🧪 測試說明
專案內含 `test_files/` 目錄，可供測試上傳功能。你可以執行以下指令重新產生測試檔案：
```bash
python3 -c "from reportlab.pdfgen import canvas; c=canvas.Canvas('test.pdf'); c.drawString(100,750,'發票 統一編號:12345678'); c.save()"
```

## 📈 未來擴充
- 整合 TF-IDF + Logistic Regression 提升分類準確度。
- 支援 OCR 處理掃描檔文字。
- 支援更多檔案格式 (HEIC, DOCX)。
- 增加多標籤 (Multi-tag) 支援。
