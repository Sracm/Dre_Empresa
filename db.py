import os
import sys
import sqlite3
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLITE_DB = os.path.join(BASE_DIR, "dre_cache.db")

class SQLiteCursorWrapper:
    def __init__(self, sqlite_cursor):
        self._cur = sqlite_cursor

    def execute(self, sql, params=None):
        sql_clean = sql.replace("%s", "?")
        if params is None:
            return self._cur.execute(sql_clean)
        elif isinstance(params, (list, tuple)):
            return self._cur.execute(sql_clean, params)
        else:
            return self._cur.execute(sql_clean, (params,))

    def executemany(self, sql, seq_of_params):
        sql_clean = sql.replace("%s", "?")
        return self._cur.executemany(sql_clean, seq_of_params)

    def fetchall(self):
        return [dict(r) for r in self._cur.fetchall()]

    def fetchone(self):
        r = self._cur.fetchone()
        return dict(r) if r else None

    def close(self):
        self._cur.close()

class SQLiteConnWrapper:
    def __init__(self, db_path):
        self._conn = sqlite3.connect(db_path, timeout=30.0)
        self._conn.row_factory = sqlite3.Row

    def cursor(self):
        return SQLiteCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def ping(self, reconnect=True):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self._conn.rollback()
        else:
            self._conn.commit()
        self._conn.close()

def get_db_connection():
    host = os.getenv("MARIADB_HOST", "192.168.1.22")
    try:
        conn = pymysql.connect(
            host=host,
            user=os.getenv("MARIADB_USER", "antonio"),
            password=os.getenv("MARIADB_PASSWORD", "yzmpq100"),
            port=int(os.getenv("MARIADB_PORT", 3306)),
            database=os.getenv("MARIADB_DB", "dre_empresa"),
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=2,
            read_timeout=3,
            write_timeout=3
        )
        return conn
    except Exception:
        if os.path.exists(SQLITE_DB):
            return SQLiteConnWrapper(SQLITE_DB)
        raise
