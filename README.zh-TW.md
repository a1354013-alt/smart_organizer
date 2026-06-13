# Smart Organizer

Smart Organizer 是一個 local-first 的安全檔案整理助理。它的重點不是直接刪檔，而是先幫你掃描、分析、預覽，再把你確認過的檔案移到可復原的隔離區。

## 專案亮點

- 安全優先：`scan -> dry-run -> execute -> quarantine -> restore` 全流程都以可逆操作為前提。
- 可解釋：用明確規則產生分類、候選原因與報表，不靠黑箱刪檔。
- 降級不當機：缺少 `ffmpeg`、`poppler`、`tesseract` 時，功能會退化並提示，但不應讓整個 app 崩潰。
- 工程品質：專案以 `ruff`、`mypy`、`pytest`、`validate_release_source.py` 與 GitHub Actions Python `3.11 / 3.12 / 3.13` 做品質控管。

## 安全整理流程

- `scan`：先掃描資料夾或上傳檔案的 metadata
- `dry-run`：先預覽整理後路徑與結果摘要
- `execute`：只有在使用者確認後才真的移動檔案
- `quarantine`：所有整理動作都先進 `.smart_organizer_quarantine/`
- `restore`：需要時可還原到原路徑，若撞名則安全改名

這代表 Smart Organizer 是安全整理助理，不是直接刪除使用者檔案的工具。

## 品質檢查

```bash
python -m compileall -q .
python -m ruff check --no-cache .
python -m mypy --cache-dir=/dev/null .
python -m pytest -q
python scripts/validate_release_source.py
```

## 延伸閱讀

- 英文 README：`README.md`
- 作品集說明：`docs/PORTFOLIO_CASE_STUDY.md`
- 發行與驗證流程：`RUN_RELEASE.md`
