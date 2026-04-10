# 智慧文件與照片助理 Side Project 規劃書

**產品名稱 (暫定):** Smart File Organizer (智慧檔案整理助理)
**作者:** Manus AI
**日期:** 2025 年 12 月 30 日

---

## 1. 產品定位與功能模組拆解

本專案定位為一個可公開展示、可逐步進化的 Side Project，旨在解決個人用戶數位檔案（文件與照片）混亂的問題，核心價值在於**自動化時間提取、主題判斷與結構化命名**。

### 1.1 產品核心功能與技術選型

| 項目 | 說明 | MVP 技術選型 |
| :--- | :--- | :--- |
| **核心語言** | Python | Python 3.11+ |
| **使用者介面 (UI)** | 快速原型與展示 | Streamlit |
| **中繼資料儲存** | 檔案索引、標籤、處理結果 | SQLite |
| **檔案儲存** | 原始檔案與整理後的檔案 | 本機檔案系統 (Local Disk) |
| **文件處理** | PDF 文本提取、OCR (掃描檔) | `pypdf`, `tesseract` (或輕量級 OCR 服務) |
| **照片處理** | EXIF 提取 | `Pillow` (PIL) 或 `exifread` |
| **API (未來)** | 服務化與前後端分離 | FastAPI |

### 1.2 功能模組拆解 (MVP / V1 / V2)

我們將功能分為三個階段，確保 MVP (最小可行產品) 能在 2～4 週內完成並展示核心價值。

| 模組 | MVP (核心價值) | V1 (優化與功能擴充) | V2 (產品化與生態) |
| :--- | :--- | :--- | :--- |
| **檔案處理** | 支援 PDF/JPG/PNG 上傳與單次處理 | 支援批次處理、處理進度條、錯誤日誌 | 支援更多格式 (DOCX, HEIC, MP4) |
| **時間提取** | EXIF / 檔案時間 (Creation/Modification) | 支援 OCR 提取文件內日期、手動校正日期 | 智慧日期校正 (例如：根據上下文判斷日期) |
| **主題分類** | Rule-based (關鍵字/檔名/資料夾) | TF-IDF + Logistic Regression 輕量級模型 | LLM 語義理解分類、多模態模型 (圖文整合) |
| **資料管理** | 檔案索引、標籤儲存、結果預覽 | 標籤管理介面、手動編輯中繼資料 | 雲端同步 (S3/Drive)、多用戶支援、API 服務 |
| **UX/展示** | Streamlit 簡易介面、Demo Script | 專屬前端 (Vue/React) 介面，優化響應速度 | 完整 Web App 體驗，包含用戶登入與設定 |

---

## 2. 系統架構與完整處理流程 (Pipeline)

### 2.1 MVP 系統架構圖

本專案採用 Streamlit + Python + SQLite 的輕量級架構，專注於核心處理邏輯的實現。

```mermaid
graph TD
    A[使用者上傳檔案 (PDF/JPG/PNG)] --> B(Streamlit UI);
    B --> C{Python 後端處理服務};
    C --> D[中繼資料提取 (EXIF/檔案時間/文字)];
    D --> E[時間標準化與主題分類 (Rule-based)];
    E --> F[SQLite 資料庫 (寫入索引與標籤)];
    E --> G[檔案整理服務 (命名與移動)];
    G --> H[整理後的檔案儲存庫];
    F --> I[Streamlit UI (結果預覽/搜尋/匯出)];
    H --> I;
```

### 2.2 完整處理流程 (Pipeline)

處理流程設計為一個穩定的流水線，確保每一步的輸出都是下一階段的可靠輸入。

| 步驟 | 模組 | 說明 | 關鍵技術/依賴 |
| :--- | :--- | :--- | :--- |
| **1. 檔案接收** | Ingestion | 接收上傳檔案，暫存於 `/tmp/upload`。 | Streamlit `st.file_uploader` |
| **2. 檔案類型判斷** | Dispatcher | 判斷檔案是 `Document` (PDF) 還是 `Photo` (JPG/PNG)。 | 檔案副檔名 |
| **3. 中繼資料提取** | Extractor | 提取檔案內建資訊：照片 (EXIF)、文件 (PDF 文本)。 | `Pillow`, `pypdf` |
| **4. 時間標準化** | Date Processor | 依序：EXIF `DateTimeOriginal` → 檔案建立/修改時間 → `UnknownDate`。 | Python `os.path`, `datetime` |
| **5. 主題分類** | Classifier | 執行 Rule-based 分類邏輯，產生一組主題標籤 (Tags)。 | 核心 Python 邏輯 |
| **6. 資料庫寫入** | Persistence | 將檔案路徑、時間、標籤等中繼資料寫入 SQLite。 | `sqlite3` |
| **7. 檔案整理** | Organizer | 根據標準化結果，計算新的路徑與檔名，並執行檔案移動。 | Python `shutil` |
| **8. 結果展示** | Presentation | 在 Streamlit 介面展示整理結果、提供搜尋與匯出清單。 | Streamlit `st.dataframe` |

---

## 3. 資料夾結構與資料庫 Schema 設計

### 3.1 資料夾結構設計

資料夾結構遵循「**時間 (穩定)**」優先於「**主題 (可變)**」的原則，確保結構的穩定性與可預測性。

**根目錄:** `/home/ubuntu/SmartOrganizer_Repo`

```
SmartOrganizer_Repo/
├── 2025/
│   ├── 2025-12/
│   │   ├── 2025-12-30_合約_原始檔名.pdf
│   │   ├── 2025-12-30_旅行_原始檔名.jpg
│   │   └── ...
│   ├── 2025-11/
│   └── ...
├── 2024/
│   └── ...
└── UnknownDate/
    └── 2025-12-30_Unknown_原始檔名.png
```

**檔案命名規則 (自動命名):**
`YYYY-MM-DD_主題_原始檔名.副檔名`

*   `YYYY-MM-DD`: 標準化時間。
*   `主題`: 系統判斷出的**主要**主題 (例如：文件類選一個，照片類選一個，若有多個標籤則選置信度最高的)。
*   `原始檔名`: 保持原始檔名，避免衝突。

### 3.2 資料庫 Schema (SQLite)

採用 SQLite 儲存檔案的中繼資料，支援快速搜尋與標籤管理。

#### Table 1: `Files` (檔案主表)

| 欄位名稱 | 資料型態 | 說明 | 備註 |
| :--- | :--- | :--- | :--- |
| `file_id` | INTEGER | 主鍵 | Auto-increment |
| `original_path` | TEXT | 原始上傳路徑 | |
| `new_path` | TEXT | 整理後的新路徑 | 檔案的唯一識別 |
| `file_hash` | TEXT | 檔案內容 SHA256 Hash | 用於重複檔案偵測 (V1) |
| `file_type` | TEXT | `document` 或 `photo` | |
| `standard_date` | TEXT | 標準化日期 (YYYY-MM-DD) | 用於資料夾結構 |
| `main_topic` | TEXT | 系統判斷出的主要主題 | 用於檔案命名 |
| `extracted_text` | TEXT | 文件提取出的文字內容 | 供全文檢索 (V1) |
| `is_processed` | BOOLEAN | 是否已完成處理 | |
| `created_at` | DATETIME | 紀錄建立時間 | |

#### Table 2: `Tags` (主題標籤表)

| 欄位名稱 | 資料型態 | 說明 | 備註 |
| :--- | :--- | :--- | :--- |
| `tag_id` | INTEGER | 主鍵 | Auto-increment |
| `tag_name` | TEXT | 標籤名稱 (例如：合約、旅行) | UNIQUE |
| `tag_type` | TEXT | 標籤類型 (document/photo) | |

#### Table 3: `FileTags` (檔案與標籤關聯表)

| 欄位名稱 | 資料型態 | 說明 | 備註 |
| :--- | :--- | :--- | :--- |
| `file_id` | INTEGER | 檔案主鍵 | Foreign Key to `Files` |
| `tag_id` | INTEGER | 標籤主鍵 | Foreign Key to `Tags` |
| `confidence` | REAL | 分類置信度 (0.0 - 1.0) | MVP 可省略，V1 必備 |
| **Primary Key** | | (`file_id`, `tag_id`) | 複合主鍵 |

---

## 4. 分類邏輯與演算法設計

我們採用「**可解釋、可逐步升級**」的策略，MVP 階段專注於 Rule-based 規則打分。

### 4.1 預設主題設計 (8～12 個)

| 類型 | 預設主題 (Tag Name) | 說明 |
| :--- | :--- | :--- |
| **文件 (Document)** | `發票`, `合約`, `報價`, `請款`, `證明文件`, `會議紀錄`, `掃描`, `其他文件` | 涵蓋常見商業與個人文件類型。 |
| **照片 (Photo)** | `人物`, `美食`, `旅行`, `文件/收據`, `工作`, `截圖`, `風景`, `其他照片` | 涵蓋常見個人照片內容。 |

### 4.2 分類邏輯 Pseudo Code (Rule-based MVP)

分類器 (Classifier) 的核心是一個分數加權系統，根據特徵匹配度給予分數，選取最高分的標籤。

```python
FUNCTION classify_file(file_metadata):
    # 1. 初始化分數
    scores = {tag: 0 for tag in ALL_TAGS}
    
    # 2. 檔案類型判斷 (決定候選標籤集)
    if file_metadata.file_type == 'document':
        candidate_tags = DOCUMENT_TAGS
    else: # photo
        candidate_tags = PHOTO_TAGS

    # 3. 特徵提取與分數加權
    
    # 3.1 文件特徵 (PDF/掃描)
    if file_metadata.file_type == 'document':
        text = file_metadata.extracted_text.lower()
        
        # 關鍵字匹配 (高權重)
        if "統一編號" in text or "發票" in text:
            scores['發票'] += 10
        if "合約書" in text or "甲方" in text:
            scores['合約'] += 10
        if "報價單" in text or "總價" in text:
            scores['報價'] += 8
        
        # 掃描檔判斷 (中權重)
        if file_metadata.is_scanned: # 假設 OCR 模組能判斷
            scores['掃描'] += 5
            
    # 3.2 照片特徵 (JPG/PNG)
    if file_metadata.file_type == 'photo':
        # 檔名規則 (高權重)
        if "screenshot" in file_metadata.original_name.lower():
            scores['截圖'] += 10
        if "line" in file_metadata.original_name.lower():
            scores['截圖'] += 8 # 假設 LINE 圖片多為截圖或收據
            
        # 來源資料夾 (中權重)
        if "trip" in file_metadata.original_path.lower():
            scores['旅行'] += 5
            
        # 輕量級圖像標籤 (V1 升級點，MVP 可用簡單規則模擬)
        # if image_model_tag == 'person': scores['人物'] += 7
        
    # 4. 選擇最佳標籤
    max_score = 0
    best_tag = '其他文件' if file_metadata.file_type == 'document' else '其他照片'
    
    for tag in candidate_tags:
        if scores[tag] > max_score:
            max_score = scores[tag]
            best_tag = tag
            
    # 5. 返回結果 (MVP 階段只返回一個主要標籤)
    return best_tag, max_score

```

### 4.3 V1 升級策略：TF-IDF + Logistic Regression

在 V1 階段，我們將分類器升級為機器學習模型，以提高準確性和可擴展性。

1.  **資料準備:** 使用 MVP 階段整理好的文件 (提取的 `extracted_text`) 和手動標註的標籤作為訓練資料。
2.  **特徵工程:** 對文本進行 TF-IDF (Term Frequency-Inverse Document Frequency) 向量化。
3.  **模型訓練:** 使用 Logistic Regression (LR) 進行多分類訓練。LR 是一種輕量級且可解釋性強的模型，非常適合 Side Project。
4.  **輸出:** 模型輸出每個標籤的機率 (置信度)，我們將機率大於某個閾值 (例如 0.6) 的標籤都作為該檔案的 `FileTags` 寫入資料庫，實現多標籤。

---

## 5. UX 流程與最小可行 Demo 情境

### 5.1 UX 流程描述 (使用者怎麼用)

使用者透過 Streamlit 介面完成以下 4 個步驟：

1.  **上傳 (Upload):**
    *   使用者點擊「選擇檔案」按鈕，一次選擇多個 PDF/JPG/PNG 檔案。
    *   (可選) 設定目標儲存庫路徑 (預設為 `/home/ubuntu/SmartOrganizer_Repo`)。
2.  **處理 (Process):**
    *   使用者點擊「開始智慧整理」按鈕。
    *   介面顯示處理進度條 (例如：處理 5/20 個檔案)。
3.  **預覽與確認 (Preview & Confirm):**
    *   處理完成後，介面顯示一個表格，列出每個檔案的整理結果：
        *   原始檔名
        *   標準化日期
        *   建議新路徑
        *   建議標籤 (Tags)
    *   使用者可以手動檢查或修改標籤 (V1 功能)。
4.  **執行 (Execute):**
    *   使用者點擊「確認移動檔案」按鈕。
    *   系統執行檔案移動與命名操作，並在資料庫中標記 `is_processed = TRUE`。
    *   顯示整理完成報告，並提供「前往儲存庫」的連結。

### 5.2 最小可行 Demo 情境 (Demo Script)

這個情境展示了「時間提取」和「主題分類」兩大核心功能。

| 步驟 | 動作 (使用者) | 預期結果 (系統) | 核心功能展示 |
| :--- | :--- | :--- | :--- |
| **1. 準備** | 準備 5 個檔案：<br>1. `IMG_20251230_100000.jpg` (含 EXIF)<br>2. `Screenshot_2025-12-29.png`<br>3. `合約書_A公司.pdf` (文字型 PDF，含「合約書」關鍵字)<br>4. `2025-12-28.pdf` (掃描檔，無 EXIF/文字)<br>5. `Untitled.jpg` (無 EXIF，檔案修改時間為 2025/12/27) | 系統準備就緒，等待上傳。 | - |
| **2. 上傳** | 一次性上傳這 5 個檔案。 | 檔案暫存成功。 | 批次上傳 |
| **3. 處理** | 點擊「開始智慧整理」。 | 處理完成，顯示預覽表格。 | 核心 Pipeline 運行 |
| **4. 預覽** | 檢查預覽表格： | | |
| | `IMG_20251230_100000.jpg` | 日期: `2025-12-30` (來自 EXIF)<br>標籤: `風景` (假設預設)<br>新路徑: `2025/2025-12/2025-12-30_風景_IMG_...jpg` | **EXIF 優先** |
| | `Screenshot_2025-12-29.png` | 日期: `2025-12-29` (來自檔案時間)<br>標籤: `截圖`<br>新路徑: `2025/2025-12/2025-12-29_截圖_Screenshot_...png` | **檔名規則分類** |
| | `合約書_A公司.pdf` | 日期: `2025-12-30` (來自檔案時間)<br>標籤: `合約`<br>新路徑: `2025/2025-12/2025-12-30_合約_合約書_...pdf` | **關鍵字 Rule-based 分類** |
| | `2025-12-28.pdf` | 日期: `2025-12-28` (來自檔案時間)<br>標籤: `掃描`<br>新路徑: `2025/2025-12/2025-12-28_掃描_2025-12-28.pdf` | **掃描檔判斷** |
| | `Untitled.jpg` | 日期: `2025-12-27` (來自檔案修改時間)<br>標籤: `其他照片`<br>新路徑: `2025/2025-12/2025-12-27_其他照片_Untitled.jpg` | **檔案時間備援** |
| **5. 執行** | 點擊「確認移動檔案」。 | 檔案被移動到正確的資料夾結構中，SQLite 紀錄更新。 | 檔案整理與命名 |

---

## 6. 未來可擴充方向

本專案的架構設計具備高度可擴展性，可從 MVP 逐步進化為成熟的產品。

### 6.1 AI 升級方向

| 階段 | 模組 | 升級內容 | 說明 |
| :--- | :--- | :--- | :--- |
| **V1** | 主題分類 | **TF-IDF + Logistic Regression** | 實現多標籤分類，提高文件分類準確度。 |
| **V1** | 照片分類 | **預訓練輕量級圖像模型** | 使用如 MobileNetV2 等輕量級模型，對照片內容進行初步標籤 (例如：`person`, `food`)。 |
| **V2** | 語義理解 | **LLM 整合** | 透過 OpenAI 或其他 LLM API，對文件內容進行更深層次的語義分析，例如：判斷文件情緒、總結內容、自動生成標籤。 |
| **V2** | 異常偵測 | **Outlier Detection** | 偵測分類置信度過低的檔案，提示使用者手動檢查，優化使用者體驗。 |

### 6.2 產品化與商業模式方向

| 模式 | 說明 | 技術變更 |
| :--- | :--- | :--- |
| **SaaS 服務** | 轉變為 Web 應用程式，提供雲端儲存與同步服務。 | **API:** FastAPI (取代 Streamlit)<br>**前端:** Vue/React<br>**儲存:** TiDB/PostgreSQL + S3/GCS |
| **本機模式 (進階)** | 專注於桌面應用程式，提供背景監控與自動整理功能。 | **UI:** Electron 或 PySide/PyQt<br>**功能:** 檔案系統監控 (例如：`watchdog` 函式庫) |
| **API 服務** | 將核心處理邏輯封裝為 API，供其他應用程式或服務呼叫。 | **API:** FastAPI，提供標準化 RESTful 介面。 |

### 6.3 技術架構擴充

將 Streamlit 替換為 **FastAPI + Vue/React** 的前後端分離架構，可實現真正的多用戶、高併發與服務化。

*   **FastAPI:** 處理檔案上傳、中繼資料提取、分類邏輯等後端服務。
*   **Vue/React:** 提供更專業、響應更快的管理介面，實現標籤管理、搜尋、過濾等複雜前端功能。
*   **資料庫升級:** 從 SQLite 升級到 PostgreSQL 或 TiDB，以支援高併發讀寫和更複雜的查詢。

這個規劃書提供了一個穩固的 MVP 基礎，並為未來的產品化和技術升級指明了清晰的路徑，完全符合一個可展示、可進化的 Side Project 要求。
