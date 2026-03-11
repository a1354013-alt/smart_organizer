import sqlite3
import os
import shutil
from datetime import datetime

class StorageManager:
    def __init__(self, db_path, repo_root):
        self.db_path = db_path
        self.repo_root = repo_root
        self._init_db()

    def _init_db(self):
        """初始化 SQLite 資料庫，支援多標籤、狀態追蹤與全文檢索"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. 檔案主表 (加入 summary 欄位)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                file_id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_name TEXT,
                new_path TEXT,
                file_hash TEXT UNIQUE,
                file_type TEXT,
                standard_date TEXT,
                main_topic TEXT,
                summary TEXT,
                status TEXT DEFAULT 'PENDING',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # 2. 標籤定義表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
                tag_name TEXT UNIQUE,
                tag_type TEXT
            )
        ''')
        
        # 3. 檔案與標籤關聯表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_tags (
                file_id INTEGER,
                tag_id INTEGER,
                confidence REAL,
                PRIMARY KEY (file_id, tag_id),
                FOREIGN KEY (file_id) REFERENCES files(file_id),
                FOREIGN KEY (tag_id) REFERENCES tags(tag_id)
            )
        ''')

        # 4. 全文檢索虛擬表 (FTS5)
        cursor.execute('''
            CREATE VIRTUAL TABLE IF NOT EXISTS file_content_fts USING fts5(
                file_id UNINDEXED,
                content,
                tokenize='unicode61'
            )
        ''')
        
        conn.commit()
        conn.close()

    def check_duplicate(self, file_hash):
        """檢查檔案是否重複"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT file_id, new_path FROM files WHERE file_hash = ?', (file_hash,))
        result = cursor.fetchone()
        conn.close()
        return result

    def create_pending_record(self, record):
        """建立初始處理紀錄"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO files (original_name, file_hash, file_type, status)
                VALUES (?, ?, ?, 'PENDING')
            ''', (record['original_name'], record['file_hash'], record['file_type']))
            file_id = cursor.lastrowid
            conn.commit()
            return file_id
        except sqlite3.IntegrityError:
            return None
        finally:
            conn.close()

    def update_file_metadata(self, file_id, metadata):
        """更新檔案的中繼資料、摘要與狀態"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE files 
            SET standard_date = ?, main_topic = ?, summary = ?, status = 'PROCESSED'
            WHERE file_id = ?
        ''', (metadata['standard_date'], metadata['main_topic'], metadata.get('summary', ''), file_id))
        
        # 更新全文檢索內容
        if 'content' in metadata and metadata['content']:
            cursor.execute('INSERT OR REPLACE INTO file_content_fts (file_id, content) VALUES (?, ?)', 
                           (file_id, metadata['content']))
            
        conn.commit()
        conn.close()

    def add_tags_to_file(self, file_id, tags_with_confidence):
        """為檔案添加多個標籤"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for tag_name, confidence in tags_with_confidence.items():
            cursor.execute('INSERT OR IGNORE INTO tags (tag_name) VALUES (?)', (tag_name,))
            cursor.execute('SELECT tag_id FROM tags WHERE tag_name = ?', (tag_name,))
            tag_id = cursor.fetchone()[0]
            cursor.execute('''
                INSERT OR REPLACE INTO file_tags (file_id, tag_id, confidence)
                VALUES (?, ?, ?)
            ''', (file_id, tag_id, confidence))
        conn.commit()
        conn.close()

    def finalize_organization(self, file_id, source_path, standard_date, main_topic, original_name):
        """執行最終的檔案移動"""
        year = standard_date.split('-')[0] if standard_date and '-' in standard_date else "UnknownYear"
        month = standard_date[:7] if standard_date and len(standard_date) >= 7 else "UnknownMonth"
        target_dir = os.path.join(self.repo_root, year, month)
        os.makedirs(target_dir, exist_ok=True)
        new_filename = f"{standard_date}_{main_topic}_{original_name}"
        target_path = os.path.join(target_dir, new_filename)
        shutil.move(source_path, target_path)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE files SET new_path = ?, status = 'COMPLETED' WHERE file_id = ?
        ''', (target_path, file_id))
        conn.commit()
        conn.close()
        return target_path

    def search_content(self, query):
        """全文檢索檔案內容"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT f.*, snippet(file_content_fts, 1, '<b>', '</b>', '...', 20) as snippet
            FROM file_content_fts fts
            JOIN files f ON fts.file_id = f.file_id
            WHERE file_content_fts MATCH ?
            ORDER BY rank
        ''', (query,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    def get_all_records(self):
        """獲取所有紀錄"""
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
