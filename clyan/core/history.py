"""Clean history, disk trends, provider feedback, and trust management."""
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clean_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            op_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            predicted_size INTEGER NOT NULL,
            actual_freed INTEGER DEFAULT NULL,
            success INTEGER DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trusted_paths (
            path TEXT PRIMARY KEY,
            label TEXT DEFAULT '',
            created TEXT NOT NULL,
            reason TEXT DEFAULT ''
        )
    """)
    # Migration for columns
    for col in ["before_free", "after_free"]:
        try:
            conn.execute(f"ALTER TABLE clean_history ADD COLUMN {col} INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            pass
    conn.commit()
    return conn


def record_clean(items: list[dict], total_size: int, action: str = "delete",
                 before_free: int = 0, after_free: int = 0) -> int:
    """Record a clean operation and per-provider feedback."""
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
    op_id = cursor.lastrowid

    # Record per-provider feedback
    by_provider: dict[str, int] = {}
    for item in items:
        p = item.get("provider", "unknown")
        by_provider[p] = by_provider.get(p, 0) + item.get("size", 0)

    predicted_total = sum(by_provider.values())
    actual_total = max(delta, 0)
    for provider, predicted in by_provider.items():
        if predicted_total > 0 and actual_total > 0:
            actual_freed = int(predicted / predicted_total * actual_total)
        else:
            actual_freed = 0 if actual_total == 0 else predicted
        conn.execute(
            "INSERT INTO clean_feedback (timestamp, op_id, provider, predicted_size, actual_freed, success) VALUES (?, ?, ?, ?, ?, 1)",
            (now, op_id, provider, predicted, actual_freed),
        )

    conn.commit()
    conn.close()
    return op_id


def get_provider_feedback(provider: str, limit: int = 10) -> list[dict]:
    """Return historical feedback for a specific provider.
    
    Returns: [{
        "timestamp": "...",
        "op_id": N,
        "predicted_size": N,
        "actual_freed": N,
        "accuracy_ratio": 0.95,  # actual/predicted
    }, ...]
    """
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM clean_feedback WHERE provider = ? ORDER BY id DESC LIMIT ?",
        (provider, limit),
    ).fetchall()
    conn.close()
    results = []
    for r in rows:
        d = dict(r)
        pred = d.get("predicted_size", 0) or 0
        actual = d.get("actual_freed", 0) or 0
        d["accuracy_ratio"] = round(actual / pred, 2) if pred > 0 else 0.0
        results.append(d)
    return results


def get_all_provider_feedback(limit: int = 10) -> dict:
    """Return feedback summary for all providers that have been cleaned.
    
    Returns: {
        "total_clean_ops": N,
        "providers": {
            "pip_cache": {
                "clean_count": 3,
                "total_predicted": 5000000,
                "total_actual": 4800000,
                "avg_accuracy": 0.96,
            }, ...
        }
    }
    """
    conn = _conn()
    rows = conn.execute(
        "SELECT provider, COUNT(*) as cnt, SUM(predicted_size) as total_pred, SUM(actual_freed) as total_actual, AVG(CAST(actual_freed AS FLOAT) / CAST(MAX(predicted_size,1) AS FLOAT)) as avg_acc FROM clean_feedback GROUP BY provider ORDER BY total_pred DESC"
    ).fetchall()
    conn.close()

    providers = {}
    for r in rows:
        d = dict(r)
        providers[d["provider"]] = {
            "clean_count": d["cnt"],
            "total_predicted": d["total_pred"],
            "total_predicted_human": format_size(d["total_pred"] or 0),
            "total_actual": d["total_actual"],
            "total_actual_human": format_size(d["total_actual"] or 0),
            "avg_accuracy": round(d["avg_acc"], 2) if d["avg_acc"] else 0.0,
        }

    return {
        "total_clean_ops": conn.execute("SELECT COUNT(*) FROM clean_feedback").fetchone()[0] if 'conn' in dir() else 0,
        "providers": providers,
    }


# ── Trust management (B) ──

def trust_add(path: str, label: str = "", reason: str = "") -> bool:
    """Add a path to the trusted list. Once trusted, it won't trigger protected_warned."""
    conn = _conn()
    now = datetime.datetime.now().isoformat()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO trusted_paths (path, label, created, reason) VALUES (?, ?, ?, ?)",
            (os.path.normpath(path).lower(), label, now, reason),
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        conn.close()
        return False


def trust_remove(path: str) -> bool:
    """Remove a path from the trusted list."""
    conn = _conn()
    try:
        conn.execute("DELETE FROM trusted_paths WHERE path = ?", (os.path.normpath(path).lower(),))
        conn.commit()
        affected = conn.total_changes > 0
        conn.close()
        return affected
    except Exception:
        conn.close()
        return False


def trust_list() -> list[dict]:
    """Return all trusted paths."""
    conn = _conn()
    rows = conn.execute("SELECT * FROM trusted_paths ORDER BY created DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_trusted(path: str) -> bool:
    """Check if a path (or its parent) is in the trusted list."""
    norm = os.path.normpath(path).lower()
    conn = _conn()
    row = conn.execute("SELECT 1 FROM trusted_paths WHERE path = ?", (norm,)).fetchone()
    conn.close()
    return row is not None


# ── Existing functions ──

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
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM disk_snapshots WHERE path = ? ORDER BY id DESC LIMIT ?",
        (path, limit),
    ).fetchall()
    conn.close()
    return list(reversed([dict(r) for r in rows]))


def get_clean_impact_summary(limit: int = 10) -> dict:
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM clean_history ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    ops = [dict(r) for r in rows]
    if not ops:
        return {"total_operations": 0, "message": "No clean history yet"}
    total_freed = sum(o.get("total_size", 0) for o in ops)
    by_provider: dict[str, dict] = {}
    for op in ops:
        try:
            items = json.loads(op.get("items_json", "[]"))
        except Exception:
            items = []
        for item in items:
            p = item.get("provider", "unknown")
            if p not in by_provider:
                by_provider[p] = {"count": 0, "total_freed": 0}
            by_provider[p]["count"] += 1
            by_provider[p]["total_freed"] += item.get("size", 0)
    provider_ranking = sorted(by_provider.items(), key=lambda x: -x[1]["total_freed"])
    return {
        "total_operations": len(ops),
        "total_freed": total_freed,
        "total_freed_human": format_size(total_freed),
        "most_reclaimed_providers": [
            {"provider": p, "freed": d["total_freed"],
             "freed_human": format_size(d["total_freed"]),
             "count": d["count"]}
            for p, d in provider_ranking[:8]
        ],
    }
