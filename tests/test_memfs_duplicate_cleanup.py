import hashlib
import threading

from storage import StorageManager


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _minimal_pdf_bytes() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


def test_create_temp_file_memfs_duplicate_orphan_cleanup_does_not_crash():
    """
    重點覆蓋：
    - self._mem_files 模式下 temp_path 為字串（mem://...）
    - 併發 duplicate cleanup 分支會嘗試刪除孤兒 temp_path
    - 不可再使用 Path.exists()/unlink()，避免 string attribute error
    """
    storage = StorageManager(":memory:", ":memory:", ":memory:")

    payload = _minimal_pdf_bytes()
    file_hash = _sha256(payload)

    results = []
    errors = []

    barrier = threading.Barrier(2)

    original_get_connection = storage._get_connection

    class _ProxyCursor:
        def __init__(self, cursor):
            self._cursor = cursor
            self._last_sql = ""
            self._waited = False

        def execute(self, sql, params=()):
            self._last_sql = str(sql)
            return self._cursor.execute(sql, params)

        def fetchone(self):
            row = self._cursor.fetchone()
            # 只在「第一次 pre-check SELECT」且結果為 None 時同步兩個 thread，
            # 以確保兩邊都能通過 pre-check，進而覆蓋後續 duplicate/orphan cleanup 分支。
            if (
                not self._waited
                and row is None
                and "FROM files WHERE file_hash" in self._last_sql
            ):
                self._waited = True
                barrier.wait(timeout=5)
            return row

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class _ProxyConn:
        def __init__(self, conn):
            self._conn = conn

        def cursor(self):
            return _ProxyCursor(self._conn.cursor())

        def __getattr__(self, name):
            return getattr(self._conn, name)

    def patched_get_connection(*args, **kwargs):
        return _ProxyConn(original_get_connection(*args, **kwargs))

    storage._get_connection = patched_get_connection

    def worker(name: str):
        try:
            results.append(storage.create_temp_file(name, payload, file_hash, "document"))
        except Exception as e:  # pragma: no cover
            errors.append(e)

    t1 = threading.Thread(target=worker, args=("a.pdf",))
    t2 = threading.Thread(target=worker, args=("b.pdf",))
    t1.start()
    t2.start()

    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors
    assert len(results) == 2
    assert any(r.get("success") is True for r in results)
    assert any(r.get("success") is False and r.get("reason") == "DUPLICATE" for r in results)
