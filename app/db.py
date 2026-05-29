"""PostgreSQL-backed key-value store using SQLAlchemy Core.

All storage modules use these helpers as a DB-first layer, falling back to
the local filesystem when SKILL_DATABASE_URL is not set (local development).
"""
from __future__ import annotations

import json
import os
from pathlib import Path as _Path
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


def _fs_path(namespace: str, key: str) -> _Path:
    """Filesystem path for a (namespace, key) pair used when no DB is configured."""
    safe_ns = namespace.replace("/", os.sep)
    return _Path(settings.data_dir) / "kv" / safe_ns / f"{key}.json"


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
        p = _fs_path(namespace, key)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT data FROM kv_store WHERE namespace = :ns AND key = :key"),
            {"ns": namespace, "key": key},
        ).fetchone()
        return row[0] if row else None


def db_set(namespace: str, key: str, data: Any) -> None:
    engine = _get_engine()
    if engine is None:
        p = _fs_path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data), encoding="utf-8")
        return
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO kv_store (namespace, key, data)
                VALUES (:ns, :key, CAST(:data AS jsonb))
                ON CONFLICT (namespace, key) DO UPDATE
                SET data = EXCLUDED.data, updated_at = now()
            """),
            {"ns": namespace, "key": key, "data": json.dumps(data)},
        )
        conn.commit()


def db_delete(namespace: str, key: str) -> None:
    engine = _get_engine()
    if engine is None:
        p = _fs_path(namespace, key)
        p.unlink(missing_ok=True)
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
        d = _fs_path(namespace, "__sentinel__").parent
        if not d.exists():
            return []
        return [
            json.loads(f.read_text(encoding="utf-8"))
            for f in sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime)
        ]
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
        d = _fs_path(namespace, "__sentinel__").parent
        if not d.exists():
            return []
        return [
            (f.stem, json.loads(f.read_text(encoding="utf-8")))
            for f in sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime)
        ]
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
        p = _fs_path(namespace, key)
        p.parent.mkdir(parents=True, exist_ok=True)
        existing = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        if not isinstance(existing, list):
            existing = [existing]
        existing.extend(new_items)
        p.write_text(json.dumps(existing), encoding="utf-8")
        return
    with engine.connect() as conn:
        conn.execute(
            text("""
                INSERT INTO kv_store (namespace, key, data)
                VALUES (:ns, :key, CAST(:items AS jsonb))
                ON CONFLICT (namespace, key) DO UPDATE
                SET data       = kv_store.data || CAST(:items AS jsonb),
                    updated_at = now()
            """),
            {"ns": namespace, "key": key, "items": json.dumps(new_items)},
        )
        conn.commit()
