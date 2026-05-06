# Smart Organizer (v2.8.4)

Smart Organizer 是一個以 Streamlit 為介面的檔案整理工具，支援上傳分析、預覽確認、執行整理、搜尋與整理紀錄查詢。專案保留規則分類、PDF/OCR、影片 metadata/縮圖與 crash-safe finalize 流程。

## UI 架構

- `app_main.py`：Streamlit 入口，負責 page config、初始化服務、session state、sidebar 與 tabs 掛載。
- `ui_home.py`：首頁與 sidebar。
- `ui_upload.py`：上傳分析。
- `ui_review.py`：預覽確認。
- `ui_execute.py`：執行整理。
- `ui_search.py`：搜尋。
- `ui_records.py`：整理紀錄。
- `ui_common.py`：共用 UI helper、CSS、folder scan helper、`UIContext`。
- `ui_state.py`：`session_state` 初始化與 review state reset。

## 主要模組

- `core.py` / `core_processor.py`：metadata 擷取、OCR、影片工具整合、分類規則。
- `services.py` 與 `services_*`：上傳分析、確認流程、整理執行。
- `storage.py` 與 `storage_*`：暫存檔、資料庫、搜尋索引、finalize/recovery。
- `create_release_zip.ps1`：runtime/demo release zip allowlist 打包腳本。

## 安裝

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
```

## 執行

```bash
streamlit run app.py
```

## 測試指令

```bash
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

常用驗收：

```bash
python -m compileall -q .
python -m pytest -q
python -m ruff check .
python -m mypy .
```

## 確認流程

`ui_review.py` 會在按下「確認無誤，進行整理」時呼叫：

```python
build_confirmed_results(
    analysis_results,
    processor=processor,
    selected_topics=selected_topics,
    summaries=st.session_state.review_summaries,
)
```

`services_review.build_confirmed_results(...)` 會套用：

- 使用者選定的主題
- review 階段產生或輸入的摘要
- `manual_override` 與同步後的 `tag_scores`

產出的 `AnalysisResult` 結構可直接交給 `finalize_batch(...)` 進入 execute flow。

## 影片處理

- `VIDEO_TOOL_TIMEOUT_SECONDS` 集中管理 ffmpeg/ffprobe timeout，預設 10 秒。
- 若 ffmpeg/ffprobe 不存在，影片 metadata 與縮圖流程會優雅 fallback，不會卡住整個分析流程。
- 影片測試以 mock `subprocess.run(...)` 為主，避免依賴長時間真實影片處理。

## 交付前檢查

交付內容不可包含：

- `tmp_test_write/`
- `__pycache__/`
- `*.pyc`
- `*.pyc.*`
- `.pytest_cache/`
- `.ruff_cache/`
- `.mypy_cache/`

另外也應排除：

- `uploads/`
- `repo/`
- `dist/`
- `build/`
- `*.db`
- `*.sqlite`
- `*.sqlite3`
- `*.log`
- `.env`
- `.env.*`

對應規則已寫入：

- `.gitignore`
- `.gitattributes`
- `tests/test_delivery_cleanliness.py`
- `create_release_zip.ps1`

## Release

建立 runtime/demo zip（僅限 source repo）：

```powershell
powershell -ExecutionPolicy Bypass -File .\create_release_zip.ps1
```

或：

```bash
python scripts/create_release_zip.py
```

腳本採 allowlist 打包，只包含執行 UI 與核心流程所需檔案，並支援相對或絕對 `OutputDir`。

重要說明：

- 官方 release zip 是 runtime/demo 執行包，不是打包工具包。
- `create_release_zip.ps1` 只能在 source repo 執行。
- 解壓後的 release zip 只負責安裝 runtime 依賴與啟動 App，不負責再次打包。
- release zip 內不包含 `scripts/`、tests、CI 設定或 dev tooling。

release zip 的啟動與 smoke test 請依 [RUN_RELEASE.md](./RUN_RELEASE.md)。
