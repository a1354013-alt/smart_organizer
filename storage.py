import sqlite3
import os
import shutil
import logging
from datetime import datetime

# 設定 Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class StorageManager:
    def __init__(self, db_path, repo_root):
        self.db_path = db_path
        self.repo_root = repo_root
        self._init_db()

    def _init_db(self):
        """初始化資料庫，明確區分 temp_path 與 final_path"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 檔案主表：新增 temp_path 與 final_path
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

            # FTS5 虛擬表
            cursor.execute('''
                CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
                    file_id UNINDEXED,
                    content,
                    tokenize='unicode61'
                )
            ''')
            
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"資料庫初始化失敗: {e}")
            raise

    def check_duplicate(self, file_hash):
        """檢查檔案是否重複，返回 final_path"""
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

    def create_pending_record(self, record):
        """上傳後立即寫入 temp_path"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO files (original_name, temp_path, file_hash, file_type, status)
                VALUES (?, ?, ?, ?, 'PENDING')
            ''', (record['original_name'], record['temp_path'], record['file_hash'], record['file_type']))
            file_id = cursor.lastrowid
            conn.commit()
            conn.close()
            return file_id
        except Exception as e:
            logger.error(f"建立 Pending 紀錄失敗: {e}")
            return None

    def get_file_by_id(self, file_id):
        """從資料庫獲取單一檔案的所有資訊 (唯一來源策略)"""
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
        """更新分析結果"""
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
            if not file_info or not os.path.exists(file_info['temp_path']):
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
        """修復 FTS5 查詢，使用 bm25 排序"""
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            # 使用 bm25(file_content_fts) 進行排序，這是 FTS5 的標準做法
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

    def cleanup_orphaned_uploads(self, upload_dir):
        """清理資料庫中不存在或已完成的暫存檔"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('SELECT temp_path FROM files WHERE temp_path IS NOT NULL')
            valid_temp_paths = set(row[0] for row in cursor.fetchall())
            conn.close()

            for filename in os.listdir(upload_dir):
                file_path = os.path.join(upload_dir, filename)
                if os.path.isfile(file_path) and file_path not in valid_temp_paths:
                    os.remove(file_path)
                    logger.info(f"已清理孤立暫存檔: {file_path}")
        except Exception as e:
            logger.error(f"清理暫存檔失敗: {e}")
