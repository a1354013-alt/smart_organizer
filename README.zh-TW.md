# 智慧檔案整理助理 Smart Organizer

Smart Organizer 是一個以本機優先為核心的檔案整理工具，適合整理下載資料夾、混合文件資料夾，或作為作品集展示的安全整理流程示範。它會先掃描與預覽，再把你選擇的檔案移到隔離區，不會直接刪除檔案。

## 專案是什麼

- 掃描本機資料夾，找出久未使用或偏大的檔案
- 顯示候選檔案、建議與原因，先複查再決定
- 整理動作採用隔離區，不直接永久刪除
- 可還原隔離檔案，並匯出 Markdown / CSV 報表
- 支援上傳 PDF、圖片、影片做分析與分類建議
- 介面支援 `zh-TW` 與 `en`，預設為繁體中文

## 如何安裝

建議使用 Python `3.11`。

```bash
python -m pip install -r requirements.txt
```

## 如何啟動

```bash
streamlit run app.py
```

啟動後可在 Sidebar 最上方切換介面語言：

- `繁體中文`
- `English`

## 如何掃描 demo folder

先建立示範資料夾：

```bash
python scripts/create_demo_folder.py
```

再啟動應用程式：

```bash
streamlit run app.py
```

進入後在「資料夾掃描」頁籤中：

1. 輸入 `demo_files` 的路徑
2. 按「開始掃描」
3. 在候選檔案區預覽建議與原因
4. 如需整理，按「移至隔離區」
5. 需要時可到右側區塊還原檔案，或匯出報表

## 安全原則

- 不直接刪除使用者檔案
- 所有整理動作都先移到 `.smart_organizer_quarantine/`
- 還原時會避免覆蓋既有檔案
- 報表與紀錄保留整理歷程，方便複查與展示

## 選用依賴

以下工具不是必裝，但安裝後可提升分析品質：

- `Tesseract`：OCR 文字辨識
- `Poppler`：PDF 預覽與影像轉換
- `FFmpeg` / `ffprobe`：影片中繼資料與縮圖

如果沒有安裝，系統會採取保守降級，不應讓主要流程直接崩潰。

## i18n 支援

目前提供兩種介面語言：

- `zh-TW`
- `en`

翻譯集中管理於：

- [i18n.py](/D:/git/smart_organizer/i18n.py)
- [locales/zh-TW.json](/D:/git/smart_organizer/locales/zh-TW.json)
- [locales/en.json](/D:/git/smart_organizer/locales/en.json)

主要 UI 文案透過 `t(key, **kwargs)` 取得，若翻譯缺漏會安全 fallback，不會讓 UI crash。
