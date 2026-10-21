"""
db.py — Gerenciador Oficial de Conexões de Banco de Dados (MQ Hair Company)
Banco Oficial: MariaDB Corporativo (tabela dre_data e tabelas analíticas DRE).
O SQLite NÃO é o banco oficial deste projeto. Todas as consultas conectam-se
obrigatoriamente ao MariaDB oficial.
"""

import os
import sys
import threading
import pymysql
import pymysql.cursors
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

_thread_local = threading.local()

def _create_mariadb_connection():
    """Cria uma nova conexão TCP direta com o servidor MariaDB oficial."""
    host = os.getenv("MARIADB_HOST", "192.168.1.22")
    user = os.getenv("MARIADB_USER", "antonio")
    password = os.getenv("MARIADB_PASSWORD", "yzmpq100")
    port = int(os.getenv("MARIADB_PORT", 3306))
    database = os.getenv("MARIADB_DB", "dre_empresa")

    try:
        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            port=port,
            database=database,
            cursorclass=pymysql.cursors.DictCursor,
            charset="utf8mb4",
            connect_timeout=8,
            read_timeout=90,
            write_timeout=90,
            autocommit=True
        )
        return conn
    except Exception as e:
        raise ConnectionError(
            f"[BANCO OFICIAL MARIADB] Falha ao conectar ao servidor oficial em {host}:{port}/{database}: {e}"
        ) from e

class PooledMariaDBConnection:
    """
    Wrapper thread-safe para reutilização de conexão com o MariaDB.
    Elimina a latência repetitiva de handshake TCP (~450ms) mantendo o socket
    ativo por thread e verificando a integridade (ping) antes de cada cursor.
    """
    def __init__(self, raw_conn):
        self._raw = raw_conn

    def _ensure_connected(self):
        try:
            self._raw.ping(reconnect=False)
        except Exception:
            try:
                self._raw.close()
            except Exception:
                pass
            self._raw = _create_mariadb_connection()

    def cursor(self, cursor=None):
        self._ensure_connected()
        return self._raw.cursor(cursor or pymysql.cursors.DictCursor)

    def commit(self):
        try:
            return self._raw.commit()
        except Exception:
            pass

    def rollback(self):
        try:
            return self._raw.rollback()
        except Exception:
            pass

    def close(self):
        # Mantém a conexão ativa no pool da thread para reaproveitamento ultra-rápido (< 20ms)
        pass

    def real_close(self):
        """Fecha fisicamente o socket TCP."""
        try:
            self._raw.close()
        except Exception:
            pass

    def ping(self, reconnect=True):
        self._ensure_connected()

    def __enter__(self):
        self._ensure_connected()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()

def get_db_connection():
    """
    Retorna a conexão oficial do MariaDB ativa para a thread atual.
    Garante acesso aos dados oficiais e oficiais apenas do MariaDB.
    """
    conn = getattr(_thread_local, "mariadb_conn", None)
    if conn is None:
        raw = _create_mariadb_connection()
        conn = PooledMariaDBConnection(raw)
        _thread_local.mariadb_conn = conn
    return conn
