import sqlite3
import threading

from .config import settings

_local = threading.local()


def conn() -> sqlite3.Connection:
    """One read-only connection per thread (FastAPI runs sync routes in a threadpool)."""
    c = getattr(_local, "c", None)
    if c is None:
        c = sqlite3.connect(f"file:{settings.db_path}?mode=ro", uri=True, check_same_thread=False)
        c.row_factory = sqlite3.Row
        _local.c = c
    return c
