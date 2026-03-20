import sqlite3
import os
import shutil
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from core import FileUtils

# 設定 Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 7  # 再次升級版本以引入 moving_target_path 欄位

class StorageManager:
    def __init__(self, db_path, repo_root, upload_dir):
        self.db_path = db_path
        self.repo_root = Path(repo_root)
        self.upload_dir = Path(upload_dir)
        
        # 確保目錄存在
        self.repo_root.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        
        self._init_db()
        self._check_migration()

    def _get_connection(self, timeout=30000):
        """【併發優化】統一獲取連線，啟用 WAL 模式、Foreign Keys 與 Timeout"""
        try:
            conn = sqlite3.connect(self.db_path, timeout=timeout/1000)
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.execute(f"PRAGMA busy_timeout={timeout};")
            return conn
        except Exception as e:
            logger.error(f"獲取資料庫連線失敗: {e}")
            raise

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
                    temp_path TEXT,
                    final_path TEXT,
                    moving_target_path TEXT,
                    file_hash TEXT UNIQUE,
                    file_type TEXT,
                    standard_date TEXT,
                    main_topic TEXT,
                    summary TEXT,
                    is_scanned INTEGER DEFAULT 0,
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
            
            if version < CURRENT_SCHEMA_VERSION:
                logger.info(f"執行資料庫 Migration: V{version} -> V{CURRENT_SCHEMA_VERSION}")
                
                # 補齊 files 表欄位 (通用邏輯)
                cursor.execute("PRAGMA table_info(files)")
                columns = [col[1] for col in cursor.fetchall()]
                new_cols = [
                    ('temp_path', 'TEXT'), ('final_path', 'TEXT'), ('moving_target_path', 'TEXT'),
                    ('file_type', 'TEXT'), ('standard_date', 'TEXT'), ('main_topic', 'TEXT'), 
                    ('summary', 'TEXT'), ('is_scanned', 'INTEGER DEFAULT 0'), ('status', "TEXT DEFAULT 'PENDING'")
                ]
                for col_name, col_type in new_cols:
                    if col_name not in columns:
                        cursor.execute(f"ALTER TABLE files ADD COLUMN {col_name} {col_type}")
                
                # V6/V7: 強化 FTS 欄位與 Cascade (如果之前沒做成功)
                if version < 7:
                    try:
                        # 1. 處理 file_tags 的 Cascade
                        cursor.execute("CREATE TABLE IF NOT EXISTS file_tags_backup AS SELECT * FROM file_tags")
                        cursor.execute("DROP TABLE IF EXISTS file_tags")
                        cursor.execute('''
                            CREATE TABLE file_tags (
                                file_id INTEGER, tag_id INTEGER, confidence REAL,
                                PRIMARY KEY (file_id, tag_id),
                                FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
                                FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
                            )
                        ''')
                        cursor.execute("INSERT INTO file_tags SELECT * FROM file_tags_backup")
                        cursor.execute("DROP TABLE file_tags_backup")

                        # 2. 擴充 FTS 表欄位並安全遷移數據
                        cursor.execute("CREATE TABLE IF NOT EXISTS fts_migration_backup(rowid INTEGER PRIMARY KEY, content TEXT)")
                        cursor.execute("PRAGMA table_info(file_content_fts)")
                        fts_cols = [c[1] for c in cursor.fetchall()]
                        if 'content' in fts_cols:
                            cursor.execute("INSERT OR REPLACE INTO fts_migration_backup(rowid, content) SELECT rowid, content FROM file_content_fts")
                        
                        cursor.execute("DROP TABLE IF EXISTS file_content_fts")
                        cursor.execute('''
                            CREATE VIRTUAL TABLE file_content_fts USING fts5(
                                original_filename, title, summary, content, tokenize='unicode61'
                            )
                        ''')
                        cursor.execute('''
                            INSERT INTO file_content_fts(rowid, original_filename, title, summary, content)
                            SELECT f.file_id, f.original_name, f.main_topic, f.summary, COALESCE(b.content, '')
                            FROM files f
                            LEFT JOIN fts_migration_backup b ON f.file_id = b.rowid
                        ''')
                        cursor.execute("DROP TABLE fts_migration_backup")
                    except Exception as mig_err:
                        logger.warning(f"V7 Migration 部分失敗: {mig_err}")

                cursor.execute('UPDATE sys_config SET value = ? WHERE key = "schema_version"', (str(CURRENT_SCHEMA_VERSION),))
                conn.commit()
        except Exception as e:
            logger.error(f"Migration 執行失敗: {e}")
        finally:
            if conn: conn.close()

    def create_temp_file(self, uploaded_file_name, file_content, file_hash, file_type):
        """【v2.7.2 鋼鐵加固】先查後寫 + BEGIN IMMEDIATE 交易，徹底消除 Race Condition"""
        temp_path = None
        part_path = None
        conn = None
        try:
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
            safe_name = FileUtils.sanitize_filename(uploaded_file_name)
            unique_temp_name = f"{file_hash[:8]}_{safe_name}"
            temp_path = self.upload_dir / unique_temp_name
            part_path = self.upload_dir / f"{unique_temp_name}.{uuid.uuid4().hex}.part"
            
            # 3. 寫入 .part 檔並原子替換
            if not temp_path.exists():
                with open(part_path, "wb") as f:
                    f.write(file_content)
                os.replace(part_path, temp_path)
            
            # 4. 使用 BEGIN IMMEDIATE 確保交易原子性
            try:
                cursor.execute("BEGIN IMMEDIATE")
                # 再次檢查 (Double Check)
                cursor.execute('SELECT file_id, status, final_path, temp_path FROM files WHERE file_hash = ?', (file_hash,))
                row = cursor.fetchone()
                if row:
                    conn.rollback()
                    # 【v2.7.3 強化】併發清理：若本次新寫入的 temp_path 與 DB 記錄的不一致，則刪除本次產生的孤兒檔
                    db_temp_path = row[3]
                    if temp_path and temp_path.exists() and str(temp_path) != db_temp_path:
                        try: temp_path.unlink()
                        except: pass
                    return {
                        "success": False, "reason": "DUPLICATE", "file_id": row[0], 
                        "status": row[1], "final_path": row[2]
                    }
                
                cursor.execute('''
                    INSERT INTO files (original_name, temp_path, file_hash, file_type, status)
                    VALUES (?, ?, ?, ?, 'PENDING')
                ''', (uploaded_file_name, str(temp_path), file_hash, file_type))
                file_id = cursor.lastrowid
                conn.commit()
                return {"success": True, "file_id": file_id}
            except sqlite3.IntegrityError:
                conn.rollback()
                # 雖然有 Double Check，但為了極致安全仍保留 IntegrityError 處理
                cursor.execute('SELECT file_id, status, final_path, temp_path FROM files WHERE file_hash = ?', (file_hash,))
                row = cursor.fetchone()
                # 【v2.7.3 強化】併發清理
                if row:
                    db_temp_path = row[3]
                    if temp_path and temp_path.exists() and str(temp_path) != db_temp_path:
                        try: temp_path.unlink()
                        except: pass
                return {
                    "success": False, "reason": "DUPLICATE", "file_id": row[0], 
                    "status": row[1], "final_path": row[2]
                }
        except Exception as e:
            logger.error(f"建立暫存檔案失敗: {e}")
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
            cursor.execute('''
                UPDATE files 
                SET standard_date = ?, main_topic = ?, summary = ?, is_scanned = ?, status = 'PROCESSED'
                WHERE file_id = ?
            ''', (metadata['standard_date'], metadata['main_topic'], metadata.get('summary', ''), 
                  1 if metadata.get('is_scanned') else 0, file_id))
            
            cursor.execute("SELECT content FROM file_content_fts WHERE rowid = ?", (file_id,))
            fts_row = cursor.fetchone()
            old_content = fts_row[0] if fts_row else ""
            
            cursor.execute("SELECT original_name FROM files WHERE file_id = ?", (file_id,))
            file_row = cursor.fetchone()
            original_name = file_row[0] if file_row else ""

            content = metadata.get('content', '') or old_content
            title = metadata.get('main_topic', '')
            summary = metadata.get('summary', '')

            cursor.execute('''
                INSERT OR REPLACE INTO file_content_fts (rowid, original_filename, title, summary, content)
                VALUES (?, ?, ?, ?, ?)
            ''', (file_id, original_name, title, summary, content))
            conn.commit()
        except Exception as e:
            logger.error(f"更新中繼資料失敗: {e}")
            raise
        finally:
            if conn: conn.close()

    def add_tags_to_file(self, file_id, tags_with_confidence):
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            for tag_name, confidence in tags_with_confidence.items():
                cursor.execute('INSERT OR IGNORE INTO tags (tag_name) VALUES (?)', (tag_name,))
                cursor.execute('SELECT tag_id FROM tags WHERE tag_name = ?', (tag_name,))
                tag_id = cursor.fetchone()[0]
                cursor.execute('INSERT OR REPLACE INTO file_tags (file_id, tag_id, confidence) VALUES (?, ?, ?)', 
                               (file_id, tag_id, confidence))
            conn.commit()
        except Exception as e:
            logger.error(f"添加標籤失敗: {e}")
        finally:
            if conn: conn.close()

    def _recover_moving_file(self, file_id, file_info):
        """【v2.7.3 重構】專門處理 MOVING 狀態的 Recovery 邏輯"""
        if file_info.get("status") != "MOVING" or not file_info.get("moving_target_path"):
            return None
            
        moving_target = file_info["moving_target_path"]
        temp_path = file_info.get("temp_path")
        temp_exists = temp_path and os.path.exists(temp_path)
        target_exists = os.path.exists(moving_target)
        
        conn = None
        try:
            if target_exists and not temp_exists:
                logger.info(f"偵測到 Recovery: 檔案已搬移成功但 DB 未更新 (ID: {file_id})")
                conn = self._get_connection()
                conn.execute('''
                    UPDATE files SET final_path = ?, temp_path = NULL, moving_target_path = NULL, status = 'COMPLETED' 
                    WHERE file_id = ?
                ''', (moving_target, file_id))
                conn.commit()
                return moving_target
            elif temp_exists:
                if target_exists:
                    logger.warning(f"偵測到異常狀態: 來源與目標同時存在 (ID: {file_id})，回退至 PROCESSED 供重新檢查")
                else:
                    logger.info(f"偵測到 Recovery: 搬移中斷且目標不存在，回退狀態 (ID: {file_id})")
                
                conn = self._get_connection()
                conn.execute("UPDATE files SET status = 'PROCESSED', moving_target_path = NULL WHERE file_id = ?", (file_id,))
                conn.commit()
            else:
                # 【v2.7.4 強化】雙失蹤處理：來源與目標皆不存在，強制回退狀態避免卡死
                logger.warning(f"偵測到嚴重異常: 來源與目標皆不存在 (ID: {file_id})，強制回退狀態")
                conn = self._get_connection()
                conn.execute("UPDATE files SET status = 'PROCESSED', moving_target_path = NULL WHERE file_id = ?", (file_id,))
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
                if os.path.exists(file_info["final_path"]):
                    return file_info["final_path"]
            
            # 2. Recovery 檢查
            recovered_path = self._recover_moving_file(file_id, file_info)
            if recovered_path:
                return recovered_path
            
            # 重新獲取資訊 (若 Recovery 執行了回退)
            file_info = self.get_file_by_id(file_id)

            # 3. 計算目標路徑
            if not standard_date or standard_date == "UnknownDate":
                year, month = "UnknownYear", "UnknownMonth"
            else:
                year = standard_date.split('-')[0] if '-' in standard_date else "UnknownYear"
                month = standard_date[:7] if len(standard_date) >= 7 else "UnknownMonth"
            
            target_dir = self.repo_root / year / month
            target_dir.mkdir(parents=True, exist_ok=True)
            
            base_filename = FileUtils.sanitize_filename(f"{standard_date}_{main_topic}_{original_name}")
            target_path = str(FileUtils.get_unique_path(target_dir / base_filename))

            if not file_info['temp_path'] or not os.path.exists(file_info['temp_path']):
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
                    shutil.move(temp_path, target_path)
                except Exception as move_err:
                    if not os.path.exists(target_path):
                        conn.execute("UPDATE files SET status = 'PROCESSED', moving_target_path = NULL WHERE file_id = ?", (file_id,))
                        conn.commit()
                    raise move_err

                # 階段三: 標記為 COMPLETED
                conn.execute('''
                    UPDATE files SET final_path = ?, temp_path = NULL, moving_target_path = NULL, status = 'COMPLETED' 
                    WHERE file_id = ?
                ''', (target_path, file_id))
                conn.commit()
                return target_path
            finally:
                if conn: conn.close()
                
        except Exception as e:
            logger.error(f"整理檔案失敗: {file_id}, 錯誤: {e}")
            raise

    def search_content(self, query):
        """【防禦性 API】內部強制執行 FTS 轉義"""
        conn = None
        try:
            safe_query = FileUtils.escape_fts_query(query)
            # 【v2.7.4 強化】空查詢防禦：若轉義後為空字串，直接回傳空列表
            if not safe_query or not safe_query.strip():
                return []
            conn = self._get_connection()
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.*, snippet(file_content_fts, 3, '<b>', '</b>', '...', 20) as snippet
                FROM file_content_fts
                JOIN files f ON file_content_fts.rowid = f.file_id
                WHERE file_content_fts MATCH ?
                ORDER BY bm25(file_content_fts)
            ''', (safe_query,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"全文檢索失敗: {e}")
            return []
        finally:
            if conn: conn.close()

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
    def cleanup_orphaned_uploads(self, preview_ttl_days=7):
        """【v2.7.2 強化】收窄安全邊界，僅清理符合命名規則的暫存檔"""
        import re
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute('SELECT temp_path FROM files WHERE temp_path IS NOT NULL')
            valid_temp_paths = set(row[0] for row in cursor.fetchall())
            # 【v2.7 修正】改用精確檔名比對
            valid_temp_names = {Path(v).name for v in valid_temp_paths}
        except Exception as e:
            logger.error(f"清理暫存檔失敗(讀 DB): {e}")
            return
        finally:
            if conn: conn.close()

        now = time.time()
        ttl_sec = preview_ttl_days * 24 * 3600

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
                        p.unlink()
                        logger.info(f"已清理孤立暫存檔: {p_str} (年齡: {int(age_sec)}s)")
                    except Exception as e:
                        logger.warning(f"刪除暫存檔失敗 {p_str}: {e}")

        preview_dir = self.upload_dir / "previews"
        if preview_dir.exists():
            for pattern in ("*.png", "*.jpg", "*.jpeg"):
                for p in preview_dir.glob(pattern):
                    p_str = str(p)
                    # 【v2.7 修正】精確還原暫存檔名，避免 replace 誤傷檔名中的副檔名字串
                    name = p.name
                    if name.startswith("preview_"):
                        name = name[len("preview_"):]
                    temp_basename = Path(name).stem
                    
                    try:
                        too_old = (now - p.stat().st_mtime) > ttl_sec
                    except:
                        too_old = True
                    
                    # 【v2.7 修正】精確比對檔名
                    is_orphan = temp_basename not in valid_temp_names
                    
                    if too_old or is_orphan:
                        try:
                            p.unlink()
                            logger.info(f"已清理孤立預覽圖: {p_str}")
                        except Exception as e:
                            logger.warning(f"刪除預覽圖失敗 {p_str}: {e}")
