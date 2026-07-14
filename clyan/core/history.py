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
            undone INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def record_clean(items: list[dict], total_size: int, action: str = "delete") -> int:
    conn = _conn()
    now = datetime.datetime.now().isoformat()
    summary = f"deleted {len(items)} items, {format_size(total_size)}"
    cursor = conn.execute(
        "INSERT INTO clean_history (timestamp, action, summary, items_json, total_size, item_count) VALUES (?, ?, ?, ?, ?, ?)",
        (now, action, summary, json.dumps(items), total_size, len(items)),
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


