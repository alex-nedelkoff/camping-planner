"""Postgres connection pool + schema bootstrap (used when STORAGE_BACKEND=postgres)."""
from __future__ import annotations

from pathlib import Path

from app import config

_pool = None
_SCHEMA = Path(__file__).with_name("schema.sql")


def _get_pool():
    global _pool
    if _pool is None:
        from psycopg_pool import ConnectionPool
        if not config.DATABASE_URL:
            raise RuntimeError("DATABASE_URL is required for STORAGE_BACKEND=postgres")
        _pool = ConnectionPool(config.DATABASE_URL, min_size=1, max_size=5, open=True)
    return _pool


def reset_pool() -> None:
    """Drop the cached pool (tests / config changes)."""
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = None


def connection():
    """Context manager yielding a pooled connection. Transaction-scoped:
    commits on clean block exit, rolls back on exception."""
    return _get_pool().connection()


def ensure_schema() -> None:
    sql = _SCHEMA.read_text()
    statements = [stmt.strip() for stmt in sql.split(";") if stmt.strip()]
    with connection() as conn:
        for stmt in statements:
            conn.execute(stmt)
