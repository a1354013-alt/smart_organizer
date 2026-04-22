import sqlite3
import os
import shutil
import logging
import time
import uuid
from pathlib import Path
from core import FileUtils

logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 13
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class SearchContentError(RuntimeError):
    pass


def _log_context(**fields):
    parts = [f"{key}={value}" for key, value in fields.items() if value not in (None, "", [])]
    return f" [{', '.join(parts)}]" if parts else ""

class StorageManager:
    def __init__(self, db_path, repo_root, upload_dir):
        self.db_path = db_path
        self._db_uri = False
        self._keepalive_conn = None

        # 測試/受限環境支援：允許使用 SQLite shared in-memory DB
        if str(self.db_path) == ":memory:":
            self.db_path = f"file:smart_organizer_memdb_{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._db_uri = True
        elif str(self.db_path).startswith("file:"):
            self._db_uri = True
        self.repo_root = Path(repo_root)
        self.upload_dir = Path(upload_dir)

        # 測試支援：提供 in-memory 檔案系統（避免受限環境無法刪除暫存檔造成污染）
        self._mem_files = None
        if str(repo_root) == ":memory:" or str(upload_dir) == ":memory:":
            self._mem_files = {}
            self.repo_root = Path("mem://repo")
            self.upload_dir = Path("mem://uploads")
        
        # 確保目錄存在
        if self._mem_files is None:
            self.repo_root.mkdir(parents=True, exist_ok=True)
            self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        # shared in-memory 需要至少一條連線存活，否則 DB 會被銷毀
        if self._db_uri and "mode=memory" in str(self.db_path):
            try:
                self._keepalive_conn = sqlite3.connect(self.db_path, uri=True)
            except Exception as e:
                logger.warning(f"建立 in-memory keepalive 連線失敗（將回退一般連線行為）: {e}")
                self._keepalive_conn = None

        self._init_db()
        self._check_migration()

    def _get_connection(self, timeout=30000):
        """【併發優化】統一獲取連線，啟用 WAL 模式、Foreign Keys 與 Timeout"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=timeout/1000, uri=self._db_uri)
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except sqlite3.OperationalError as e:
                # 某些受限檔案系統/權限環境無法使用 WAL（會出現 disk I/O error）
                logger.warning(f"WAL 模式不可用，回退為 DELETE journal_mode: {e}")
                try:
                    conn.execute("PRAGMA journal_mode=DELETE;")
                except Exception:
                    pass

            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(f"PRAGMA busy_timeout={timeout};")
            return conn
        except Exception as e:
            logger.error(f"獲取資料庫連線失敗: {e}")
            raise

    def _is_mem_path(self, path_value):
        return isinstance(path_value, str) and path_value.startswith("mem://")

    def _path_exists(self, path_value):
        if not path_value:
            return False
        if self._mem_files is not None and self._is_mem_path(path_value):
            return path_value in self._mem_files
        return os.path.exists(path_value)

    def _move_path(self, src, dst):
        if self._mem_files is not None and self._is_mem_path(src) and self._is_mem_path(dst):
            self._mem_files[dst] = self._mem_files.pop(src)
            return
        shutil.move(src, dst)

    def _copy_path(self, src, dst):
        """統一複製檔案：支援實體路徑與 mem:// 路徑。"""
        if self._mem_files is not None and self._is_mem_path(src) and self._is_mem_path(dst):
            self._mem_files[dst] = bytes(self._mem_files.get(src, b""))
            return
        shutil.copy2(src, dst)

    def _remove_path(self, path_value):
        """統一刪除檔案：支援實體路徑與 mem:// 路徑。"""
        if not path_value:
            return
        if self._mem_files is not None and self._is_mem_path(path_value):
            try:
                self._mem_files.pop(path_value, None)
            except Exception:
                pass
            return
        try:
            os.remove(path_value)
        except FileNotFoundError:
            return

    def _merge_last_error(self, existing, addition, max_len=400):
        """合併 last_error 訊息：保留既有診斷，不重複灌水，並限制長度。"""
        addition = (addition or "").strip()
        if not addition:
            return (existing or "").strip()[:max_len] or None

        existing_str = (existing or "").strip()
        if not existing_str:
            merged = addition
        else:
            if addition in existing_str:
                merged = existing_str
            else:
                merged = f"{existing_str} | {addition}"

        if len(merged) > max_len:
            merged = merged[:max_len] + "..."
        return merged

    def _recovery_diag(self, summary):
        """統一 Recovery 類診斷訊息格式（對使用者可見，避免 traceback 細節）。"""
        summary = (summary or "").strip()
        if not summary:
            return None
        return f"Recovery: {summary}"

    def _init_db(self):
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('CREATE TABLE IF NOT EXISTS sys_config (key TEXT PRIMARY KEY, value TEXT)')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_name TEXT,
                    safe_name TEXT,
                    final_name TEXT,
                    temp_path TEXT,
                    final_path TEXT,
                    preview_path TEXT,
                    moving_target_path TEXT,
                    file_hash TEXT UNIQUE,
                    file_type TEXT,
                    standard_date TEXT,
                    main_topic TEXT,
                    summary TEXT,
                    classification_reason TEXT,
                    final_decision_reason TEXT,
                    manual_override INTEGER DEFAULT 0,
                    is_scanned INTEGER DEFAULT 0,
                    last_error TEXT,
                    status TEXT DEFAULT 'PENDING',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('CREATE TABLE IF NOT EXISTS tags (tag_id INTEGER PRIMARY KEY AUTOINCREMENT, tag_name TEXT UNIQUE)')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS file_tags (
                    file_id INTEGER, tag_id INTEGER, confidence REAL,
                    PRIMARY KEY (file_id, tag_id),
                    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
                )
            ''')
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
                    original_filename,
                    title,
                    summary,
                    content,
                    tokenize='unicode61'
                )
            ''')
            cursor.execute('INSERT OR IGNORE INTO sys_config (key, value) VALUES (?, ?)', ('schema_version', str(CURRENT_SCHEMA_VERSION)))
            conn.commit()
        except Exception as e:
            logger.error(f"資料庫初始化失敗: {e}")
            raise
        finally:
            if conn: conn.close()

    def _check_migration(self):
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM sys_config WHERE key = "schema_version"')
            row = cursor.fetchone()
            version = int(row[0]) if row else 1
            
            # 補齊 files 表欄位（必做）：避免新 DB 已標記最新 schema_version 但欄位缺失造成 runtime 崩潰。
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            new_cols = [
                ('safe_name', 'TEXT'), ('final_name', 'TEXT'), ('classification_reason', 'TEXT'), ('final_decision_reason', 'TEXT'),
                ('temp_path', 'TEXT'), ('final_path', 'TEXT'), ('preview_path', 'TEXT'), ('moving_target_path', 'TEXT'),
                ('file_type', 'TEXT'), ('standard_date', 'TEXT'), ('main_topic', 'TEXT'),
                ('summary', 'TEXT'), ('is_scanned', 'INTEGER DEFAULT 0'), ('status', "TEXT DEFAULT 'PENDING'"),
                ('last_error', 'TEXT'), ('manual_override', 'INTEGER DEFAULT 0'),
                ('decision_source', 'TEXT'), ('decision_updated_at', 'TEXT'),
                ('last_manual_topic', 'TEXT'), ('last_manual_reason', 'TEXT'),
            ]
            for col_name, col_type in new_cols:
                if col_name not in columns:
                    cursor.execute(f"ALTER TABLE files ADD COLUMN {col_name} {col_type}")

            if version < CURRENT_SCHEMA_VERSION:
                logger.info(f"執行資料庫 Migration: V{version} -> V{CURRENT_SCHEMA_VERSION}")

                # V6/V7: 強化 FTS 欄位與 Cascade (如果之前沒做成功)
                if version < 7:
                    # 1. 處理 file_tags 的 Cascade
                    cursor.execute("CREATE TABLE IF NOT EXISTS file_tags_backup AS SELECT * FROM file_tags")
                    cursor.execute("DROP TABLE IF EXISTS file_tags")
                    cursor.execute(
                        """
                        CREATE TABLE file_tags (
                            file_id INTEGER, tag_id INTEGER, confidence REAL,
                            PRIMARY KEY (file_id, tag_id),
                            FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
                            FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
                        )
                        """
                    )
                    cursor.execute("INSERT INTO file_tags SELECT * FROM file_tags_backup")
                    cursor.execute("DROP TABLE file_tags_backup")

                    # 2. 擴充 FTS 表欄位並安全遷移數據
                    cursor.execute("CREATE TABLE IF NOT EXISTS fts_migration_backup(rowid INTEGER PRIMARY KEY, content TEXT)")
                    cursor.execute("PRAGMA table_info(file_content_fts)")
                    fts_cols = [c[1] for c in cursor.fetchall()]
                    if "content" in fts_cols:
                        cursor.execute(
                            "INSERT OR REPLACE INTO fts_migration_backup(rowid, content) SELECT rowid, content FROM file_content_fts"
                        )

                    cursor.execute("DROP TABLE IF EXISTS file_content_fts")
                    cursor.execute(
                        """
                        CREATE VIRTUAL TABLE file_content_fts USING fts5(
                            original_filename, title, summary, content, tokenize='unicode61'
                        )
                        """
                    )
                    cursor.execute(
                        """
                        INSERT INTO file_content_fts(rowid, original_filename, title, summary, content)
                        SELECT f.file_id, f.original_name, f.main_topic, f.summary, COALESCE(b.content, '')
                        FROM files f
                        LEFT JOIN fts_migration_backup b ON f.file_id = b.rowid
                        """
                    )
                    cursor.execute("DROP TABLE fts_migration_backup")

                cursor.execute('UPDATE sys_config SET value = ? WHERE key = "schema_version"', (str(CURRENT_SCHEMA_VERSION),))

            conn.commit()
        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.error(f"Migration 執行失敗（已回滾並中止啟動）: {e}")
            raise RuntimeError(f"Database migration failed: {e}") from e
        finally:
            if conn: conn.close()

    def _normalize_uploaded_bytes(self, file_content):
        if isinstance(file_content, memoryview):
            return file_content.tobytes()
        if isinstance(file_content, bytearray):
            return bytes(file_content)
        if isinstance(file_content, bytes):
            return file_content
        return bytes(file_content)

    def _detect_extension(self, filename):
        return Path(filename or "").suffix.lower()

    def _validate_upload(self, uploaded_file_name, file_content):
        original_name = Path(uploaded_file_name or "").name
        safe_name = FileUtils.sanitize_filename(original_name)
        ext = self._detect_extension(safe_name)
        payload = self._normalize_uploaded_bytes(file_content)

        if not safe_name.strip():
            raise ValueError("檔名不可為空")
        if ext not in FileUtils.ALLOWED_UPLOAD_EXTENSIONS:
            raise ValueError(f"不支援的檔案格式: {ext or 'unknown'}")
        if not payload:
            raise ValueError("檔案不可為空")
        if len(payload) > MAX_UPLOAD_BYTES:
            raise ValueError(f"檔案大小超過上傳硬限制 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB")

        if ext == ".pdf" and not payload.startswith(b"%PDF-"):
            raise ValueError("PDF 檔案簽章不正確")
        if ext == ".png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("PNG 檔案簽章不正確")
        if ext in {".jpg", ".jpeg"} and not payload.startswith(b"\xff\xd8\xff"):
            raise ValueError("JPEG 檔案簽章不正確")

        return original_name, safe_name, payload

    def _merge_main_topic_into_tags(self, main_topic, tags_with_confidence):
        merged = {}
        for tag_name, confidence in (tags_with_confidence or {}).items():
            if tag_name:
                try:
                    merged[tag_name] = float(confidence)
                except (TypeError, ValueError):
                    merged[tag_name] = 0.0

        if main_topic:
            current_max = max(merged.values(), default=0.0)
            merged[main_topic] = max(merged.get(main_topic, 0.0), current_max, 1.0)

        return merged

    def _replace_file_tags(self, cursor, file_id, tags_with_confidence):
        cursor.execute('DELETE FROM file_tags WHERE file_id = ?', (file_id,))
        for tag_name, confidence in tags_with_confidence.items():
            cursor.execute('INSERT OR IGNORE INTO tags (tag_name) VALUES (?)', (tag_name,))
            cursor.execute('SELECT tag_id FROM tags WHERE tag_name = ?', (tag_name,))
            tag_id = cursor.fetchone()[0]
            cursor.execute(
                'INSERT INTO file_tags (file_id, tag_id, confidence) VALUES (?, ?, ?)',
                (file_id, tag_id, confidence)
            )

    def path_exists(self, path):
        """Public wrapper: check existence for both filesystem paths and mem:// paths."""
        return self._path_exists(path)

    def _infer_file_type(self, filename, provided=None):
        """
        Storage/domain must not blindly trust UI-provided file_type.
        Infer from filename extension; fall back to provided only if safe.
        """
        name = str(filename or "")
        ext = os.path.splitext(name)[1].lower()
        if ext in {".jpg", ".jpeg", ".png"}:
            return "photo"
        if ext == ".pdf":
            return "document"
        if ext in {".mp4", ".mov", ".mkv"}:
            return "video"
        if provided in {"photo", "document", "video"}:
            return str(provided)
        return "document"

    def create_temp_file(self, uploaded_file_name, file_content, file_hash, file_type):
        """【v2.7.2 鋼鐵加固】先查後寫 + BEGIN IMMEDIATE 交易，徹底消除 Race Condition"""
        temp_path = None
        part_path = None
        conn = None
        try:
            original_name, safe_name, payload = self._validate_upload(uploaded_file_name, file_content)
            final_file_type = self._infer_file_type(original_name, file_type)
            # 1. 先檢查 Hash 是否已存在 (快速路徑)
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT file_id, status, final_path, temp_path FROM files WHERE file_hash = ?', (file_hash,))
            row = cursor.fetchone()
            if row:
                # 【v2.7.3 強化】快速路徑併發清理：若檔案已存在且檔名不同，則不執行後續寫入
                return {
                    "success": False, "reason": "DUPLICATE", "file_id": row[0], 
                    "status": row[1], "final_path": row[2]
                }

            # 2. 準備寫入檔案
            unique_temp_name = f"{file_hash[:8]}_{safe_name}"
            if self._mem_files is not None:
                temp_path = f"mem://uploads/{unique_temp_name}"
                part_path = None
            else:
                temp_path = self.upload_dir / unique_temp_name
                part_path = self.upload_dir / f"{unique_temp_name}.{uuid.uuid4().hex}.part"
             
            # 3. 寫入 .part 檔並原子替換
            if self._mem_files is not None:
                if temp_path not in self._mem_files:
                    self._mem_files[temp_path] = payload
            elif not temp_path.exists():
                try:
                    with open(part_path, "wb") as f:
                        f.write(payload)
                    os.replace(part_path, temp_path)
                except PermissionError as e:
                    # 受限環境可能禁止 rename/replace（WinError 5）；降級為直接寫入目標檔
                    logger.warning(f"os.replace 失敗，改用直接寫入 temp_path: {e}")
                    with open(temp_path, "wb") as f:
                        f.write(payload)
                    if part_path and part_path.exists():
                        try:
                            os.remove(part_path)
                        except Exception:
                            pass
            
            # 4. 使用 BEGIN IMMEDIATE 確保交易原子性
            try:
                # shared-cache/in-memory 等場景下可能出現 SQLITE_LOCKED（busy_timeout 不一定生效）；
                # 這裡做小幅重試以提升併發穩定性（不改狀態機/表設計）。
                begin_err = None
                for attempt in range(10):
                    try:
                        cursor.execute("BEGIN IMMEDIATE")
                        begin_err = None
                        break
                    except sqlite3.OperationalError as oe:
                        begin_err = oe
                        if "locked" in str(oe).lower():
                            time.sleep(0.01 * (attempt + 1))
                            continue
                        raise
                if begin_err is not None:
                    raise begin_err
                # 再次檢查 (Double Check)
                cursor.execute('SELECT file_id, status, final_path, temp_path FROM files WHERE file_hash = ?', (file_hash,))
                row = cursor.fetchone()
                if row:
                    conn.rollback()
                    # 【v2.7.3 強化】併發清理：若本次新寫入的 temp_path 與 DB 記錄的不一致，則刪除本次產生的孤兒檔
                    db_temp_path = row[3]
                    if temp_path and str(temp_path) != db_temp_path and self._path_exists(temp_path):
                        try:
                            self._remove_path(temp_path)
                        except Exception:
                            pass
                    return {
                        "success": False, "reason": "DUPLICATE", "file_id": row[0], 
                        "status": row[1], "final_path": row[2]
                    }
                
                cursor.execute('''
                    INSERT INTO files (original_name, safe_name, temp_path, file_hash, file_type, status)
                    VALUES (?, ?, ?, ?, ?, 'PENDING')
                ''', (original_name, safe_name, str(temp_path), file_hash, final_file_type))
                file_id = cursor.lastrowid
                conn.commit()
                logger.info(
                    "create_temp_file success%s",
                    _log_context(
                        file_id=file_id,
                        original_name=original_name,
                        file_type=final_file_type,
                        temp_path=str(temp_path),
                    ),
                )
                return {"success": True, "file_id": file_id}
            except sqlite3.IntegrityError:
                conn.rollback()
                # 雖然有 Double Check，但為了極致安全仍保留 IntegrityError 處理
                cursor.execute('SELECT file_id, status, final_path, temp_path FROM files WHERE file_hash = ?', (file_hash,))
                row = cursor.fetchone()
                # 【v2.7.3 強化】併發清理
                if row:
                    db_temp_path = row[3]
                    if temp_path and str(temp_path) != db_temp_path and self._path_exists(temp_path):
                        try:
                            self._remove_path(temp_path)
                        except Exception:
                            pass
                return {
                    "success": False, "reason": "DUPLICATE", "file_id": row[0], 
                    "status": row[1], "final_path": row[2]
                }
        except Exception as e:
            logger.error(
                "建立暫存檔案失敗%s: %s",
                _log_context(original_name=uploaded_file_name, file_hash=str(file_hash)[:8]),
                e,
            )
            if part_path and part_path.exists():
                try: os.remove(part_path)
                except: pass
            return {"success": False, "reason": "ERROR", "message": str(e)}
        finally:
            if conn: conn.close()

    def get_file_path(self, file_id):
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT final_path, temp_path FROM files WHERE file_id = ?', (file_id,))
            row = cursor.fetchone()
            if row:
                return row[0] if row[0] else row[1]
            return None
        except Exception as e:
            logger.error(f"獲取檔案路徑失敗: {e}")
            return None
        finally:
            if conn: conn.close()

    def get_file_by_id(self, file_id):
        conn = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM files WHERE file_id = ?', (file_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"獲取檔案資訊失敗: {e}")
            return None
        finally:
            if conn: conn.close()

    def update_file_metadata(self, file_id, metadata):
        """【v2.7 修正】FTS 同步更新，防止 content 被洗空"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            normalized_date = FileUtils.normalize_standard_date(metadata.get('standard_date'))
            main_topic = metadata.get('main_topic', '')
            preview_path = metadata.get('preview_path')
            tag_scores = self._merge_main_topic_into_tags(main_topic, metadata.get('tag_scores'))
            manual_override = metadata.get("manual_override")
            manual_override_val = None if manual_override is None else (1 if manual_override else 0)

            # Decision history / observability (minimal, schema-added via migration)
            decision_source = metadata.get("decision_source")
            last_manual_topic = metadata.get("last_manual_topic")
            last_manual_reason = metadata.get("last_manual_reason")
            if manual_override_val == 1:
                decision_source = decision_source or "MANUAL_OVERRIDE"
                last_manual_topic = last_manual_topic or main_topic
                last_manual_reason = last_manual_reason or metadata.get("final_decision_reason")
            cursor.execute('''
                UPDATE files 
                SET standard_date = ?,
                    main_topic = ?,
                    summary = ?,
                    preview_path = ?,
                    classification_reason = COALESCE(?, classification_reason),
                    final_decision_reason = COALESCE(?, final_decision_reason),
                    manual_override = COALESCE(?, manual_override),
                    decision_source = COALESCE(?, decision_source),
                    decision_updated_at = CASE WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE decision_updated_at END,
                    last_manual_topic = COALESCE(?, last_manual_topic),
                    last_manual_reason = COALESCE(?, last_manual_reason),
                    is_scanned = ?,
                    status = CASE
                        WHEN status = 'COMPLETED' THEN 'COMPLETED'
                        ELSE 'PROCESSED'
                    END
                WHERE file_id = ?
            ''', (
                normalized_date,
                main_topic,
                metadata.get('summary', ''),
                preview_path,
                metadata.get('classification_reason'),
                metadata.get('final_decision_reason'),
                manual_override_val,
                decision_source,
                decision_source,
                last_manual_topic,
                last_manual_reason,
                1 if metadata.get('is_scanned') else 0,
                file_id
            ))
            
            cursor.execute("SELECT content FROM file_content_fts WHERE rowid = ?", (file_id,))
            fts_row = cursor.fetchone()
            old_content = fts_row[0] if fts_row else ""
            
            cursor.execute("SELECT original_name FROM files WHERE file_id = ?", (file_id,))
            file_row = cursor.fetchone()
            original_name = file_row[0] if file_row else ""

            content = metadata.get('content', '') or old_content
            title = main_topic
            summary = metadata.get('summary', '')

            cursor.execute('''
                INSERT OR REPLACE INTO file_content_fts (rowid, original_filename, title, summary, content)
                VALUES (?, ?, ?, ?, ?)
            ''', (file_id, original_name, title, summary, content))
            if tag_scores:
                self._replace_file_tags(cursor, file_id, tag_scores)
            conn.commit()
            cursor.execute("SELECT status FROM files WHERE file_id = ?", (file_id,))
            status_row = cursor.fetchone()
            current_status = status_row[0] if status_row else None
            logger.info(
                "update_file_metadata success%s",
                _log_context(
                    file_id=file_id,
                    status=current_status,
                    main_topic=main_topic,
                    decision_source=decision_source,
                    preview_path=preview_path,
                ),
            )

        except Exception as e:
            logger.error(
                "更新中繼資料失敗%s: %s",
                _log_context(file_id=file_id, main_topic=main_topic, decision_source=decision_source),
                e,
            )
            raise
        finally:
            if conn: conn.close()

    def add_tags_to_file(self, file_id, tags_with_confidence, main_topic=None):
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            merged_tags = self._merge_main_topic_into_tags(main_topic, tags_with_confidence)
            self._replace_file_tags(cursor, file_id, merged_tags)
            conn.commit()
        except Exception as e:
            logger.error(f"添加標籤失敗: {e}")
            raise
        finally:
            if conn: conn.close()

    def _recover_moving_file(self, file_id, file_info):
        """【v2.7.3 重構】專門處理 MOVING 狀態的 Recovery 邏輯"""
        if file_info.get("status") != "MOVING" or not file_info.get("moving_target_path"):
            return None
            
        moving_target = file_info["moving_target_path"]
        temp_path = file_info.get("temp_path")
        temp_exists = temp_path and self._path_exists(temp_path)
        target_exists = self._path_exists(moving_target)
        existing_last_error = file_info.get("last_error")
        
        conn = None
        try:
            if target_exists and not temp_exists:
                logger.info(f"偵測到 Recovery: 檔案已搬移成功但 DB 未更新 (file_id={file_id})")
                conn = self._get_connection()
                conn.execute('''
                    UPDATE files SET final_path = ?, temp_path = NULL, moving_target_path = NULL, status = 'COMPLETED' 
                    WHERE file_id = ?
                ''', (moving_target, file_id))
                conn.commit()
                return moving_target
            elif temp_exists:
                if target_exists:
                    logger.warning(f"偵測到異常狀態: 來源與目標同時存在 (file_id={file_id})，嘗試清理目標殘留後回退至 PROCESSED 供重新檢查")
                    # 第二層防護：若目標殘留仍存在，優先清理目標，保留 temp 作為可重試來源
                    cleanup_failed = False
                    try:
                        self._remove_path(moving_target)
                        logger.warning(f"Recovery 已清理目標殘留 (file_id={file_id}): {moving_target}")
                    except Exception:
                        cleanup_failed = True
                        logger.warning(f"Recovery 清理目標殘留失敗 (file_id={file_id}): {moving_target}", exc_info=True)
                else:
                    logger.info(f"偵測到 Recovery: 搬移中斷且目標不存在，回退狀態 (file_id={file_id})")
                 
                conn = self._get_connection()
                # 可觀測性：若 recovery 清理目標殘留失敗，寫入簡潔摘要到 last_error（不塞 traceback）
                if target_exists and cleanup_failed:
                    diag = self._recovery_diag(f"目標殘留清理失敗（請人工處理）：{Path(moving_target).name}")
                    merged = self._merge_last_error(existing_last_error, diag)
                    conn.execute(
                        "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ? WHERE file_id = ?",
                        (merged, file_id),
                    )
                else:
                    conn.execute(
                        "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL WHERE file_id = ?",
                        (file_id,),
                    )
                conn.commit()
            else:
                # 【v2.7.4 強化】雙失蹤處理：來源與目標皆不存在，強制回退狀態避免卡死
                logger.warning(f"偵測到嚴重異常: 來源與目標皆不存在 (file_id={file_id})，強制回退狀態")
                conn = self._get_connection()
                diag = self._recovery_diag("來源與目標皆不存在（可能檔案遺失或被移除），已回退 PROCESSED 供重試/修復")
                merged = self._merge_last_error(existing_last_error, diag)
                conn.execute(
                    "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ? WHERE file_id = ?",
                    (merged, file_id),
                )
                conn.commit()
            return None
        except Exception as e:
            logger.error(f"Recovery 執行失敗 (ID: {file_id}): {e}")
            return None
        finally:
            if conn: conn.close()

    def finalize_organization(self, file_id, standard_date, main_topic, original_name):
        """【v2.7.3 重構】基於狀態機的檔案整理終端化流程"""
        try:
            file_info = self.get_file_by_id(file_id)
            if not file_info:
                raise ValueError(f"找不到檔案 ID: {file_id}")
            
            # 1. 冪等性檢查
            if file_info.get("status") == "COMPLETED" and file_info.get("final_path"):
                if self._path_exists(file_info["final_path"]):
                    return file_info["final_path"]
            
            # 2. Recovery 檢查
            recovered_path = self._recover_moving_file(file_id, file_info)
            if recovered_path:
                return recovered_path
            
            # 重新獲取資訊 (若 Recovery 執行了回退)
            file_info = self.get_file_by_id(file_id)

            # 3. 計算目標路徑
            normalized_date, year, month = FileUtils.get_date_directory_parts(standard_date)
            
            target_dir = self.repo_root / year / month
            if self._mem_files is None:
                target_dir.mkdir(parents=True, exist_ok=True)
            
            safe_name = file_info.get("safe_name") or FileUtils.sanitize_filename(Path(original_name or file_info.get("original_name") or "").name)
            final_name = FileUtils.sanitize_filename(f"{normalized_date}_{main_topic}_{safe_name}")

            if self._mem_files is not None:
                base_target = f"mem://repo/{year}/{month}/{final_name}"
                if base_target not in self._mem_files:
                    target_path = base_target
                else:
                    stem, ext = os.path.splitext(final_name)
                    counter = 1
                    while True:
                        candidate_name = f"{stem}_{counter}{ext}"
                        candidate_path = f"mem://repo/{year}/{month}/{candidate_name}"
                        if candidate_path not in self._mem_files:
                            target_path = candidate_path
                            final_name = candidate_name
                            break
                        counter += 1
            else:
                target_path = str(FileUtils.get_unique_path(target_dir / final_name))

            if not file_info['temp_path'] or not self._path_exists(file_info['temp_path']):
                raise FileNotFoundError(f"找不到暫存檔案: {file_info.get('temp_path')}")

            temp_path = file_info['temp_path']

            # 4. 三階段狀態機流程
            conn = self._get_connection()
            try:
                # 階段一: 標記為 MOVING
                conn.execute('''
                    UPDATE files SET status = 'MOVING', moving_target_path = ? WHERE file_id = ?
                ''', (target_path, file_id))
                conn.commit()

                # 階段二: 執行搬移
                try:
                    self._move_path(temp_path, target_path)
                except PermissionError as move_err:
                    # 受限環境可能禁止 rename/move；降級為 copy + (盡力)刪除原檔
                    # 注意：mem:// 與實體路徑都必須走 abstraction，避免混用 shutil/os API。
                    logger.warning(f"搬移權限不足，改用 copy (file_id={file_id}): {move_err}")
                    try:
                        self._copy_path(temp_path, target_path)
                    except Exception as copy_err:
                        # partial copy failure 保護：若 target 已寫出一部分，避免留下髒 target 造成後續 recovery/重試混亂
                        logger.error("copy fallback 失敗", exc_info=True)
                        if self._path_exists(target_path):
                            try:
                                self._remove_path(target_path)
                                logger.warning(f"已清理 partial target (file_id={file_id}): {target_path}")
                            except Exception:
                                logger.warning("清理 partial target 失敗（忽略）", exc_info=True)

                        msg = str(copy_err)
                        if len(msg) > 400:
                            msg = msg[:400] + "..."
                        conn.execute(
                            "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ? WHERE file_id = ?",
                            (msg, file_id),
                        )
                        conn.commit()
                        raise copy_err
                    try:
                        self._remove_path(temp_path)
                    except Exception:
                        pass
                except Exception as move_err:
                    if not self._path_exists(target_path):
                        msg = str(move_err)
                        if len(msg) > 400:
                            msg = msg[:400] + "..."
                        conn.execute(
                            "UPDATE files SET status = 'PROCESSED', moving_target_path = NULL, last_error = ? WHERE file_id = ?",
                            (msg, file_id),
                        )
                        conn.commit()
                    raise move_err

                # 階段三: 標記為 COMPLETED
                conn.execute('''
                    UPDATE files
                    SET final_name = ?,
                        final_path = ?,
                        temp_path = NULL,
                        moving_target_path = NULL,
                        last_error = NULL,
                        status = 'COMPLETED'
                    WHERE file_id = ?
                ''', (final_name, target_path, file_id))
                conn.commit()
                logger.info(
                    "finalize_organization success%s",
                    _log_context(
                        file_id=file_id,
                        status="COMPLETED",
                        temp_path=temp_path,
                        final_path=target_path,
                    ),
                )
                return target_path
            finally:
                if conn: conn.close()
                
        except Exception as e:
            logger.error(f"整理檔案失敗 (file_id={file_id}): {e}")
            try:
                conn2 = self._get_connection()
                try:
                    # 不大改狀態機：只補上可診斷資訊，並確保可重試（通常會停留在 PROCESSED 或 MOVING）
                    msg = str(e)
                    if len(msg) > 400:
                        msg = msg[:400] + "..."
                    conn2.execute(
                        "UPDATE files SET last_error = ? WHERE file_id = ?",
                        (msg, file_id),
                    )
                    conn2.commit()
                finally:
                    conn2.close()
            except Exception:
                logger.warning("寫入 last_error 失敗（忽略，不影響主流程）", exc_info=True)
            raise

    def _escape_like(self, s):
        return (s or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    # 搜尋排序權重（保持穩定可預期，測試鎖住）
    _META_SCORE_ORIGINAL_NAME = 2.0
    _META_SCORE_MAIN_TOPIC = 1.2
    _META_SCORE_SUMMARY = 1.0
    _META_SCORE_TAG = 0.8

    def _score_metadata_row(self, q_lower, row_dict):
        """metadata fallback 的可預期 scoring（避免散落硬編碼權重）。"""
        score = 0.0
        if q_lower in (row_dict.get("original_name") or "").lower():
            score += self._META_SCORE_ORIGINAL_NAME
        if q_lower in (row_dict.get("main_topic") or "").lower():
            score += self._META_SCORE_MAIN_TOPIC
        if q_lower in (row_dict.get("summary") or "").lower():
            score += self._META_SCORE_SUMMARY
        if q_lower in (row_dict.get("all_tags") or "").lower():
            score += self._META_SCORE_TAG
        return score

    def search_content(self, query, limit=50):
        """搜尋：FTS5 先做主查詢（不 join tags、不 group by），再用第二段查 tags，最後再做 metadata fallback。"""
        q = (query or "").strip()
        safe_query = FileUtils.escape_fts_query(q)

        # 規格：FTS query 經 escape 後為空字串，直接回傳空結果（不走 fallback）
        if not safe_query or not safe_query.strip():
            return []

        conn = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            merged = {}

            # -------- 第一階段：FTS 主體查詢（嚴禁 join tags / group by） --------
            fts_ids = []
            try:
                cursor.execute('''
                    SELECT
                        f.file_id,
                        f.original_name,
                        f.standard_date,
                        f.main_topic,
                        f.summary,
                        f.final_path,
                        f.created_at,
                        snippet(file_content_fts, 3, '<b>', '</b>', '...', 20) as snippet,
                        bm25(file_content_fts) as fts_rank
                    FROM file_content_fts
                    JOIN files f ON file_content_fts.rowid = f.file_id
                    WHERE file_content_fts MATCH ?
                    ORDER BY bm25(file_content_fts)
                    LIMIT ?
                ''', (safe_query, int(limit)))

                for row in cursor.fetchall():
                    d = dict(row)
                    rank = d.get("fts_rank")
                    try:
                        rank = float(rank) if rank is not None else 9999.0
                    except Exception:
                        rank = 9999.0
                    d["_score"] = 1.0 / (1.0 + max(rank, 0.0))
                    d["all_tags"] = None
                    merged[d["file_id"]] = d
                    fts_ids.append(d["file_id"])
            except Exception as fts_err:
                # 規格：FTS 失敗要 log 清楚，但仍允許 fallback 繼續
                logger.error(f"FTS 主查詢失敗: {fts_err}", exc_info=True)
                fts_ids = []

            # -------- 第二階段：針對 FTS 命中的 file_id 再查 tags --------
            if fts_ids:
                try:
                    placeholders = ",".join(["?"] * len(fts_ids))
                    cursor.execute(
                        f'''
                        SELECT ft.file_id, t.tag_name
                        FROM file_tags ft
                        JOIN tags t ON ft.tag_id = t.tag_id
                        WHERE ft.file_id IN ({placeholders})
                        ''',
                        tuple(fts_ids),
                    )
                    tag_map = {}
                    for file_id, tag_name in cursor.fetchall():
                        if not tag_name:
                            continue
                        tag_map.setdefault(int(file_id), []).append(tag_name)
                    for file_id in fts_ids:
                        tags = tag_map.get(int(file_id), [])
                        if tags and file_id in merged:
                            merged[file_id]["all_tags"] = ", ".join(sorted(set(tags)))
                except Exception as tag_err:
                    logger.warning(f"FTS tags 補查失敗（不影響主結果）: {tag_err}")

            # -------- fallback：metadata LIKE 搜尋（保留現有能力） --------
            like = f"%{self._escape_like(q)}%"
            cursor.execute('''
                SELECT
                    f.*,
                    GROUP_CONCAT(t.tag_name) as all_tags
                FROM files f
                LEFT JOIN file_tags ft ON f.file_id = ft.file_id
                LEFT JOIN tags t ON ft.tag_id = t.tag_id
                WHERE
                    f.original_name LIKE ? ESCAPE '\\'
                    OR COALESCE(f.summary, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(f.main_topic, '') LIKE ? ESCAPE '\\'
                    OR COALESCE(t.tag_name, '') LIKE ? ESCAPE '\\'
                GROUP BY f.file_id
                ORDER BY f.created_at DESC
                LIMIT ?
            ''', (like, like, like, like, int(limit)))

            q_lower = q.lower()
            for row in cursor.fetchall():
                d = dict(row)
                score = self._score_metadata_row(q_lower, d)

                if d["file_id"] in merged:
                    merged[d["file_id"]]["_score"] = merged[d["file_id"]].get("_score", 0.0) + score
                    if not merged[d["file_id"]].get("snippet"):
                        merged[d["file_id"]]["snippet"] = (d.get("summary") or d.get("main_topic") or "")[:120]
                    if d.get("all_tags") and not merged[d["file_id"]].get("all_tags"):
                        merged[d["file_id"]]["all_tags"] = d.get("all_tags")
                else:
                    d["snippet"] = (d.get("summary") or d.get("main_topic") or "")[:120]
                    d["_score"] = score
                    merged[d["file_id"]] = d

            results = list(merged.values())
            results.sort(key=lambda r: (r.get("_score", 0.0), r.get("created_at", "")), reverse=True)
            for r in results:
                r.pop("_score", None)
                r.pop("fts_rank", None)
            return results[: int(limit)]

        except Exception as e:
            logger.error("搜尋查詢失敗", exc_info=True)
            # 對使用者：友善訊息；詳細錯誤留在 log，避免底層 exception 外洩到 UI
            raise SearchContentError("搜尋功能暫時不可用，請稍後再試或檢查資料庫狀態。") from e
        finally:
            if conn:
                conn.close()

    def rebuild_fts_index(self):
        """重建 FTS 索引（不重跑 OCR/解析，只用 DB 現有欄位與既存 content）。"""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("DROP TABLE IF EXISTS fts_rebuild_backup")
            cursor.execute("CREATE TEMP TABLE fts_rebuild_backup AS SELECT rowid, content FROM file_content_fts")
            cursor.execute("DELETE FROM file_content_fts")
            cursor.execute('''
                INSERT INTO file_content_fts(rowid, original_filename, title, summary, content)
                SELECT
                    f.file_id,
                    COALESCE(f.original_name, ''),
                    COALESCE(f.main_topic, ''),
                    COALESCE(f.summary, ''),
                    COALESCE(b.content, '')
                FROM files f
                LEFT JOIN fts_rebuild_backup b ON f.file_id = b.rowid
            ''')
            cursor.execute("DROP TABLE IF EXISTS fts_rebuild_backup")
            conn.commit()
            return {"success": True}
        except Exception as e:
            logger.error(f"重建 FTS 索引失敗: {e}")
            if conn:
                conn.rollback()
            return {"success": False, "error": str(e)}
        finally:
            if conn:
                conn.close()

    def refresh_file_locations(self, fix_moving=True):
        """掃描並標記缺失/壞紀錄；可選擇修復 MOVING 狀態的檔案。"""
        conn = None
        summary = {"checked": 0, "recovered": 0, "missing": 0, "broken": 0}
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT file_id, status, temp_path, final_path, moving_target_path FROM files")
            rows = cursor.fetchall()

            for row in rows:
                summary["checked"] += 1
                info = dict(row)
                file_id = info["file_id"]
                status = info.get("status")
                temp_path = info.get("temp_path")
                final_path = info.get("final_path")
                moving_target = info.get("moving_target_path")

                if fix_moving and status == "MOVING" and moving_target:
                    recovered = self._recover_moving_file(file_id, info)
                    if recovered:
                        summary["recovered"] += 1
                        continue

                if status == "COMPLETED" and final_path and not self._path_exists(final_path):
                    cursor.execute("UPDATE files SET status = 'MISSING' WHERE file_id = ?", (file_id,))
                    summary["missing"] += 1
                    continue

                if status in {"PENDING", "PROCESSED"}:
                    temp_exists = temp_path and self._path_exists(temp_path)
                    final_exists = final_path and self._path_exists(final_path)
                    if not temp_exists and not final_exists:
                        cursor.execute("UPDATE files SET status = 'BROKEN' WHERE file_id = ?", (file_id,))
                        summary["broken"] += 1
                        continue

            conn.commit()
            return {"success": True, "summary": summary}
        except Exception as e:
            logger.error(f"重新整理檔案位置失敗: {e}")
            if conn:
                conn.rollback()
            return {"success": False, "error": str(e), "summary": summary}
        finally:
            if conn:
                conn.close()

    def get_all_records(self):
        conn = None
        try:
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.*, GROUP_CONCAT(t.tag_name) as all_tags
                FROM files f
                LEFT JOIN file_tags ft ON f.file_id = ft.file_id
                LEFT JOIN tags t ON ft.tag_id = t.tag_id
                GROUP BY f.file_id
                ORDER BY f.created_at DESC
            ''')
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"獲取紀錄失敗: {e}")
            return []
        finally:
            if conn: conn.close()

    def _is_preview_referenced(self, preview_path, valid_preview_paths, valid_temp_names, valid_hash_prefixes):
        if preview_path in valid_preview_paths:
            return True

        preview_name = Path(preview_path).name
        source_name = preview_name[len("preview_"):] if preview_name.startswith("preview_") else preview_name
        source_basename = Path(source_name).stem

        if source_basename in valid_temp_names:
            return True

        hash_prefix = source_basename.split("_", 1)[0].lower()
        if len(hash_prefix) == 8 and hash_prefix in valid_hash_prefixes:
            return True

        return False

    def cleanup_orphaned_uploads(self, preview_ttl_days=7, dry_run=True):
        """清理 uploads/ 孤兒檔案；預設 dry_run=True 只預覽不刪除。"""
        if self._mem_files is not None:
            return []
        import re
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT temp_path, final_path, preview_path, file_hash
                FROM files
                WHERE temp_path IS NOT NULL OR final_path IS NOT NULL OR preview_path IS NOT NULL
            ''')
            valid_temp_paths = set()
            valid_temp_names = set()
            valid_preview_paths = set()
            valid_hash_prefixes = set()
            for temp_path, final_path, preview_path, file_hash in cursor.fetchall():
                if temp_path:
                    valid_temp_paths.add(temp_path)
                    valid_temp_names.add(Path(temp_path).name)
                if preview_path:
                    valid_preview_paths.add(preview_path)
                if file_hash:
                    valid_hash_prefixes.add(file_hash[:8].lower())
        except Exception as e:
            logger.error(f"清理暫存檔失敗(讀 DB): {e}")
            return []
        finally:
            if conn: conn.close()

        now = time.time()
        ttl_sec = preview_ttl_days * 24 * 3600
        actions = []

        # 暫存檔命名規則: hash8_filename
        temp_pattern = re.compile(r"^[a-f0-9]{8}_.+")

        for p in self.upload_dir.glob("*"):
            if p.is_file():
                p_str = str(p)
                # 【v2.7.3 強化】年齡保護：僅清理建立超過 5 分鐘 (300秒) 的孤兒暫存檔，避免踩到進行中流程
                try:
                    age_sec = now - p.stat().st_mtime
                except:
                    age_sec = 0
                
                if age_sec > 300 and temp_pattern.match(p.name) and p_str not in valid_temp_paths:
                    try:
                        actions.append({"type": "temp", "path": p_str, "age_sec": int(age_sec)})
                        if not dry_run:
                            p.unlink()
                            logger.info(f"已清理孤立暫存檔: {p_str} (年齡: {int(age_sec)}s)")
                    except Exception as e:
                        logger.warning(f"刪除暫存檔失敗 {p_str}: {e}")

        preview_dir = self.upload_dir / "previews"
        if preview_dir.exists():
            for pattern in ("*.png", "*.jpg", "*.jpeg"):
                for p in preview_dir.glob(pattern):
                    p_str = str(p)
                    try:
                        too_old = (now - p.stat().st_mtime) > ttl_sec
                    except OSError:
                        too_old = True
                    
                    # 以資料庫中仍然存在的有效檔案紀錄作為準則，優先比對持久化 preview_path，
                    # 其次回退到 temp basename 與 file_hash 前綴，避免 finalized 後 preview 被誤刪。
                    is_referenced = self._is_preview_referenced(
                        p_str,
                        valid_preview_paths,
                        valid_temp_names,
                        valid_hash_prefixes
                    )
                    is_orphan = not is_referenced
                    
                    if too_old and is_orphan:
                        try:
                            actions.append({"type": "preview", "path": p_str})
                            if not dry_run:
                                p.unlink()
                                logger.info(f"已清理孤立預覽圖: {p_str}")
                        except Exception as e:
                            logger.warning(f"刪除預覽圖失敗 {p_str}: {e}")

        return actions
