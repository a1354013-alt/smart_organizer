# 📁 智慧檔案整理助理 (v2.8.4)

「智慧檔案整理助理」是一個以 **本機檔案整理/分類/搜尋/去重** 為核心的 Streamlit App：上傳或批量匯入檔案後，透過規則引擎與可選的 AI 摘要，將檔案整理到可追蹤、可重試、可維護的資料庫驅動流程中。

## 專案定位（很重要）
- 這是 **智慧檔案整理**：分類、命名、歸檔、去重、可搜尋、可追蹤決策。
- 這不是知識庫：不做筆記系統、不做跨文件關聯圖、不做長文檢索/問答產品化包裝。

## 目前支援的檔案類型與能力邊界
### 文件（Document）
- 支援：`PDF`
- 內容來源：
  - 先嘗試抽取 PDF 文字（若 PDF 本身是可選取文字）
  - 可選擇對掃描型 PDF 做「抽樣頁數」OCR（預設最多 3 頁）
- 可選擇產生 PDF 預覽圖（第一頁轉圖）

### 照片（Photo）
- 支援：`JPG/JPEG`、`PNG`
- 內容來源：
  - 讀取 EXIF 日期（若可用）
  - 可選 OCR 圖片文字（需要 tesseract）
- 預覽：照片本身即為預覽

### 影片（Video）— Phase 1（明確邊界）
- 支援：`MP4`、`MOV`、`MKV`
- 目前只做 **Phase 1（檔案層級）**：
  - 副檔名/檔名規則分類（可解釋，不做內容理解）
  - `ffprobe` 擷取容器/串流 metadata（時長/解析度/fps/codec/大小）
  - `ffmpeg` 擷取縮圖（作為預覽）
- **不做**：影片內容理解、語意切片、字幕生成、語音轉文字、鏡頭/人物辨識

## 依賴缺失時的降級行為（Graceful Degradation）
本專案設計原則是：**缺少系統依賴時，App 仍可運作，只是功能降級**。

- 缺少 `poppler`：跳過 PDF 預覽圖，其他流程照常（仍可分類/整理/搜尋）
- 缺少 `tesseract` / 語言包：OCR 停用或跳過（若 PDF/圖片本身可抽出文字，仍可搜尋）
- 缺少 `ffmpeg/ffprobe`：跳過影片縮圖與影片 metadata（影片仍可上傳與規則分類）

## 安裝與執行
### 1) 系統級依賴（OS Dependencies）
**Ubuntu/Debian**
```bash
sudo apt-get update
sudo apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-chi-tra ffmpeg
```

**macOS (Homebrew)**
```bash
brew install poppler tesseract tesseract-lang ffmpeg
```

**Windows**
- Poppler：確保 `pdftoppm.exe` 在 PATH，或設定環境變數 `POPPLER_PATH` 指向 Poppler 的 `bin`
- Tesseract：確保 `tesseract.exe` 在 PATH，並安裝繁中語言包（常見 `chi_tra`）
- ffmpeg：下載 builds 加入 PATH，或使用 `choco install ffmpeg`

### 2) Python 依賴
```bash
pip install -r requirements.txt
```

### 3) 啟動
```bash
streamlit run app.py
```

## 測試與品質門檻（CI/本機一致）
```bash
ruff check .
mypy version.py contracts.py services.py services_models.py services_analysis.py services_review.py services_finalize.py core.py core_utils.py core_classification.py core_processor.py storage.py storage_base.py storage_schema.py storage_repository.py storage_recovery.py storage_search.py storage_cleanup.py storage_manager.py async_processor.py
python -B -m pytest -q
```

> 影片相關測試在缺少 ffmpeg 時會跳過（skip），但影片的 metadata 結構契約仍會被非 ffmpeg 測試覆蓋。

## Release 交付包 vs Source Repo（交付邊界）
本專案提供兩種「可交付」形態：

1) **Source Repo（開發/測試用）**
- 含 `tests/`、`requirements-dev.txt`、`pyproject.toml`、CI 設定
- 用於跑測試、靜態檢查、開發迭代

2) **Release Zip（runtime/demo package）**
- 由 `create_release_zip.ps1` 以「允許清單」生成
- **不包含**：`tests/`、`.git/`、快取、workspace 暫存檔、開發工具
- 目標：交付可執行 demo，避免把整個 workspace 快照誤當正式交付

詳見：`RUN_RELEASE.md`、`RELEASE_PACKAGING.md`

## Architecture（精簡版）
### 分層責任
- `core*`：檔案內容/metadata 擷取、規則分類（`FileProcessor` / `FileUtils`）
- `services*`：Use case（上傳分析、人工覆寫、確認、整理落盤、重新分類）
- `storage*`：資料庫/檔案生命週期（去重、狀態機、crash-safe finalize、FTS、recovery、cleanup）
- `app_main.py`：Streamlit UI（薄控制層，盡量不承載核心決策）

### 主要資料流（Data Flow）
1. Upload/Import → `storage.create_temp_file()`：暫存檔落地 + hash 去重
2. `core.FileProcessor.extract_metadata()`：抽取 metadata / preview / OCR（可降級）
3. `core.FileProcessor.classify_multi_tag()`：規則分類（可解釋）
4. Review → `services_review.apply_manual_topic_override()`：人工覆寫主題，保留決策原因
5. Finalize → `storage.finalize_organization()`：搬移檔案到 repo 結構 + DB 狀態更新（crash-safe）
6. Search → `storage.search_content()`：FTS5 + metadata fallback（檔名/主題/摘要/標籤）

### Storage 狀態機（State Machine）
資料表 `files.status` 主要狀態：
- `PENDING`：已建立暫存檔，尚未完成 metadata/分類落庫
- `PROCESSED`：完成 metadata/分類落庫，等待整理落盤
- `MOVING`：正在搬移（crash-safe，支援 recovery）
- `COMPLETED`：已整理完成（final_path 存在）
- `MISSING`：記錄為完成但檔案遺失
- `BROKEN`：暫存與最終檔都不存在（需人工介入或重新上傳）

決策追蹤（Decision History）重點欄位：
- `decision_source`：RULE / MANUAL_OVERRIDE / RULE_RECLASSIFY / RECOVERY
- `decision_updated_at`、`last_manual_topic`、`last_manual_reason`

## 搜尋（FTS）維護說明
- `search_content()` 使用 SQLite FTS5 做全文檢索，並補上 metadata fallback（檔名/主題/摘要/標籤）
- `reconcile_fts_rows()`（UI：對齊/重建全文索引）只做：
  - rowid 對齊/補齊缺漏列
  - 從 DB 欄位（檔名/主題/摘要）重建對應欄位
  - **保留** FTS 表中既有的 `content`（不會重新讀原始檔案抽內容）

## 目前限制與後續可擴充方向（不亂吹）
目前限制
- 影片僅 Phase 1：規則分類 + ffprobe metadata + thumbnail，不含內容理解
- OCR 為抽樣策略，偏向提升可搜尋性，而非完整逐頁辨識
- 目前 cleanup 聚焦在 `uploads/` 與 `previews/` 的孤兒暫存檔，不做「長期未使用檔案」的 repo 級清理策略

後續可擴充（加分項，非本次必修）
- 更完整的批量匯入工作流與報表（但仍以整理/清理為主，不走知識庫方向）
- 更細緻的 duplicate policy（同 hash / 近似重複）與自動化清理策略（可設定保留規則）
- 更完善的 observability（結構化 log / 匯出診斷報告），提升交付時可維運性

