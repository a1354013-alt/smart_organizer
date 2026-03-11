import sqlite3
import os
import shutil
import logging
from datetime import datetime
from pathlib import Path

# 設定 Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

CURRENT_SCHEMA_VERSION = 2

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

    def _init_db(self):
        """初始化資料庫與系統配置表"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 系統配置表 (用於版本控制)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sys_config (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            
            # 檔案主表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files (
                    file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_name TEXT,
                    temp_path TEXT,
                    final_path TEXT,
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
                    FOREIGN KEY (file_id) REFERENCES files(file_id),
                    FOREIGN KEY (tag_id) REFERENCES tags(tag_id)
                )
            ''')

            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
                    file_id UNINDEXED,
                    content,
                    tokenize='unicode61'
                )
            ''')
            
            # 初始化版本號
            cursor.execute('INSERT OR IGNORE INTO sys_config (key, value) VALUES (?, ?)', ('schema_version', str(CURRENT_SCHEMA_VERSION)))
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"資料庫初始化失敗: {e}")
            raise

    def _check_migration(self):
        """簡單的 Schema Migration 策略"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM sys_config WHERE key = "schema_version"')
            row = cursor.fetchone()
            version = int(row[0]) if row else 1
            
            if version < 2:
                logger.info(f"執行 Migration: v{version} -> v2")
                # 範例：如果 v2 新增了欄位，可以在這裡執行 ALTER TABLE
                # cursor.execute('ALTER TABLE files ADD COLUMN new_col TEXT')
                cursor.execute('UPDATE sys_config SET value = ? WHERE key = "schema_version"', (str(CURRENT_SCHEMA_VERSION),))
                conn.commit()
            
            conn.close()
        except Exception as e:
            logger.error(f"Migration 檢查失敗: {e}")

    def create_temp_file(self, uploaded_file_name, file_content, file_hash, file_type):
        """
        【路徑封裝】UI 不再自己組路徑。
        傳入原始檔名與內容，由 Storage 決定存哪裡，並回傳 file_id。
        """
        try:
            # 檔名安全處理 (由 Storage 層確保)
            from core import FileProcessor
            safe_name = FileProcessor().sanitize_filename(uploaded_file_name)
            temp_path = self.upload_dir / safe_name
            
            # 寫入實體檔案
            with open(temp_path, "wb") as f:
                f.write(file_content)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO files (original_name, temp_path, file_hash, file_type, status)
                VALUES (?, ?, ?, ?, 'PENDING')
            ''', (uploaded_file_name, str(temp_path), file_hash, file_type))
            file_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return file_id
        except Exception as e:
            logger.error(f"建立暫存檔案失敗: {e}")
            return None

    def get_file_path(self, file_id):
        """
        【路徑封裝】UI 只傳 file_id，Storage 回傳目前可用的路徑 (優先回傳 final_path)。
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT final_path, temp_path FROM files WHERE file_id = ?', (file_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return row[0] if row[0] else row[1]
            return None
        except Exception as e:
            logger.error(f"獲取檔案路徑失敗: {e}")
            return None

    def check_duplicate(self, file_hash):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT file_id, final_path FROM files WHERE file_hash = ? AND status = "COMPLETED"', (file_hash,))
            result = cursor.fetchone()
            conn.close()
            return result
        except Exception as e:
            logger.error(f"重複檢查失敗: {e}")
            return None

    def get_file_by_id(self, file_id):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM files WHERE file_id = ?', (file_id,))
            row = cursor.fetchone()
            conn.close()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"獲取檔案資訊失敗: {e}")
            return None

    def update_file_metadata(self, file_id, metadata):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE files 
                SET standard_date = ?, main_topic = ?, summary = ?, is_scanned = ?, status = 'PROCESSED'
                WHERE file_id = ?
            ''', (metadata['standard_date'], metadata['main_topic'], metadata.get('summary', ''), 
                  1 if metadata.get('is_scanned') else 0, file_id))
            
            if metadata.get('content'):
                cursor.execute('INSERT OR REPLACE INTO file_content_fts (file_id, content) VALUES (?, ?)', 
                               (file_id, metadata['content']))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"更新中繼資料失敗: {e}")
            raise

    def add_tags_to_file(self, file_id, tags_with_confidence):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            for tag_name, confidence in tags_with_confidence.items():
                cursor.execute('INSERT OR IGNORE INTO tags (tag_name) VALUES (?)', (tag_name,))
                cursor.execute('SELECT tag_id FROM tags WHERE tag_name = ?', (tag_name,))
                tag_id = cursor.fetchone()[0]
                cursor.execute('INSERT OR REPLACE INTO file_tags (file_id, tag_id, confidence) VALUES (?, ?, ?)', 
                               (file_id, tag_id, confidence))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"添加標籤失敗: {e}")

    def finalize_organization(self, file_id, target_path):
        """執行最終移動並更新 final_path，清理 temp_path"""
        try:
            file_info = self.get_file_by_id(file_id)
            if not file_info or not file_info['temp_path'] or not os.path.exists(file_info['temp_path']):
                raise FileNotFoundError(f"找不到暫存檔案: {file_info.get('temp_path') if file_info else 'Unknown'}")

            # 確保目標目錄存在
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            
            # 移動檔案
            shutil.move(file_info['temp_path'], target_path)
            
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE files SET final_path = ?, temp_path = NULL, status = 'COMPLETED' WHERE file_id = ?
            ''', (target_path, file_id))
            conn.commit()
            conn.close()
            return target_path
        except Exception as e:
            logger.error(f"整理檔案失敗: {file_id}, 錯誤: {e}")
            raise

    def search_content(self, query):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('''
                SELECT f.*, snippet(file_content_fts, 1, '<b>', '</b>', '...', 20) as snippet
                FROM file_content_fts fts
                JOIN files f ON fts.file_id = f.file_id
                WHERE file_content_fts MATCH ?
                ORDER BY bm25(file_content_fts)
            ''', (query,))
            rows = cursor.fetchall()
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"全文檢索失敗: {e}")
            return []

    def get_all_records(self):
        try:
            conn = sqlite3.connect(self.db_path)
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
            conn.close()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"獲取紀錄失敗: {e}")
            return []

    def cleanup_orphaned_uploads(self):
        """清理資料庫中不存在或已完成的暫存檔"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT temp_path FROM files WHERE temp_path IS NOT NULL')
            valid_temp_paths = set(row[0] for row in cursor.fetchall())
            conn.close()

            for filename in os.listdir(self.upload_dir):
                file_path = str(self.upload_dir / filename)
                if os.path.isfile(file_path) and file_path not in valid_temp_paths:
                    # 排除 previews 目錄
                    if 'previews' in file_path: continue
                    os.remove(file_path)
                    logger.info(f"已清理孤立暫存檔: {file_path}")
        except Exception as e:
            logger.error(f"清理暫存檔失敗: {e}")
