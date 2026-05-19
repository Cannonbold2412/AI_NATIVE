"""PostgreSQL-backed key-value store using SQLAlchemy Core.

All storage modules use these helpers as a DB-first layer, falling back to
the local filesystem when SKILL_DATABASE_URL is not set (local development).
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import create_engine, text

from app.config import settings

_engine = None


def _get_engine():
    global _engine
    if _engine is None and settings.database_url:
        url = settings.database_url.replace("postgres://", "postgresql://", 1)
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def init_db() -> None:
    """Create kv_store table if it does not exist. Called once at startup."""
    engine = _get_engine()
    if engine is None:
        return
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS kv_store (
                namespace  TEXT        NOT NULL,
                key        TEXT        NOT NULL,
                data       JSONB       NOT NULL DEFAULT '{}',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (namespace, key)
            )
        """))
        conn.commit()


def db_get(namespace: str, key: str) -> Any | None:
    engine = _get_engine()
    if engine is None:
        return None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT data FROM kv_store WHERE namespace = :ns AND key = :key"),
            {"ns": namespace, "key": key},
        ).fetchone()
        return row[0] if row else None


def db_set(namespace: str, key: str, data: Any) -> None:
    engine = _get_engine()
    if engine is None:
        return
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO kv_store (namespace, key, data)
                VALUES (:ns, :key, :data::jsonb)
                ON CONFLICT (namespace, key) DO UPDATE
                SET data = EXCLUDED.data, updated_at = now()
            """),
            {"ns": namespace, "key": key, "data": json.dumps(data)},
        )
        conn.commit()


def db_delete(namespace: str, key: str) -> None:
    engine = _get_engine()
    if engine is None:
        return
    with engine.connect() as conn:
        conn.execute(
            text("DELETE FROM kv_store WHERE namespace = :ns AND key = :key"),
            {"ns": namespace, "key": key},
        )
        conn.commit()


def db_list(namespace: str) -> list[Any]:
    """Return all values in a namespace ordered by created_at."""
    engine = _get_engine()
    if engine is None:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT data FROM kv_store WHERE namespace = :ns ORDER BY created_at"),
            {"ns": namespace},
        ).fetchall()
        return [r[0] for r in rows]


def db_list_kv(namespace: str) -> list[tuple[str, Any]]:
    """Return (key, value) pairs in a namespace ordered by created_at."""
    engine = _get_engine()
    if engine is None:
        return []
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT key, data FROM kv_store WHERE namespace = :ns ORDER BY created_at"),
            {"ns": namespace},
        ).fetchall()
        return [(r[0], r[1]) for r in rows]


def db_append(namespace: str, key: str, new_items: list) -> None:
    """Append items to a JSON array stored at (namespace, key).

    Creates the row with new_items as a JSON array on first call,
    then concatenates on subsequent calls.
    """
    engine = _get_engine()
    if engine is None:
        return
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO kv_store (namespace, key, data)
                VALUES (:ns, :key, :items::jsonb)
                ON CONFLICT (namespace, key) DO UPDATE
                SET data       = kv_store.data || :items::jsonb,
                    updated_at = now()
            """),
            {"ns": namespace, "key": key, "items": json.dumps(new_items)},
        )
        conn.commit()
