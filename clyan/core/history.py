import os
import json
import sqlite3
import datetime
from pathlib import Path
from typing import Optional

import platformdirs

from ..utils.size import format_size


_DB_PATH: Optional[str] = None


def _get_db() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        data_dir = Path(platformdirs.user_data_dir("clyan", ensure_exists=True))
        _DB_PATH = str(data_dir / "clyan_history.db")
    return _DB_PATH


def _conn() -> sqlite3.Connection:
    db = _get_db()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clean_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            action TEXT NOT NULL,
            summary TEXT NOT NULL,
            items_json TEXT NOT NULL,
            total_size INTEGER NOT NULL,
            item_count INTEGER NOT NULL,
            undone INTEGER DEFAULT 0,
            before_free INTEGER DEFAULT NULL,
            after_free INTEGER DEFAULT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS disk_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            path TEXT NOT NULL,
            total_size INTEGER NOT NULL,
            free_size INTEGER NOT NULL,
            used_size INTEGER NOT NULL
        )
    """)
    # Add columns if missing (migration for existing DBs)
    for col in ["before_free", "after_free"]:
        try:
            conn.execute(f"ALTER TABLE clean_history ADD COLUMN {col} INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
    return conn


def record_clean(items: list[dict], total_size: int, action: str = "delete",
                 before_free: int = 0, after_free: int = 0) -> int:
    conn = _conn()
    now = datetime.datetime.now().isoformat()
    delta = after_free - before_free if before_free and after_free else 0
    summary = f"deleted {len(items)} items, {format_size(total_size)}"
    if delta:
        summary += f", freed {format_size(max(delta,0))} actual"
    cursor = conn.execute(
        "INSERT INTO clean_history (timestamp, action, summary, items_json, total_size, item_count, before_free, after_free) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (now, action, summary, json.dumps(items), total_size, len(items), before_free or None, after_free or None),
    )
    conn.commit()
    conn.close()
    return cursor.lastrowid


def get_history(limit: int = 20) -> list[dict]:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM clean_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_operation(op_id: int) -> Optional[dict]:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM clean_history WHERE id = ?", (op_id,)
    ).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def mark_undone(op_id: int) -> bool:
    conn = _conn()
    conn.execute("UPDATE clean_history SET undone = 1 WHERE id = ?", (op_id,))
    conn.commit()
    affected = conn.total_changes > 0
    conn.close()
    return affected


def record_disk_snapshot(path: str, total: int, free: int, used: int) -> int:
    """Save a disk usage snapshot for trend tracking."""
    conn = _conn()
    now = datetime.datetime.now().isoformat()
    cursor = conn.execute(
        "INSERT INTO disk_snapshots (timestamp, path, total_size, free_size, used_size) VALUES (?, ?, ?, ?, ?)",
        (now, path, total, free, used),
    )
    conn.commit()
    conn.close()
    return cursor.lastrowid


def get_disk_trend(path: str, limit: int = 14) -> list[dict]:
    """Return recent disk snapshots for *path*, oldest first, up to *limit*."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM disk_snapshots WHERE path = ? ORDER BY id DESC LIMIT ?",
        (path, limit),
    ).fetchall()
    conn.close()
    return list(reversed([dict(r) for r in rows]))


