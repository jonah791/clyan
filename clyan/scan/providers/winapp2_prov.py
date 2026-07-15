"""Winapp2 dynamic provider — scans using imported Winapp2 cleaner definitions.
Optimized: pre-filters by file existence before spawning threads.
"""
import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total


def _scan_winapp2(root: str) -> list[CacheItem]:
    """Scan imported Winapp2 cleaners — only returns items for installed apps."""
    results = []
    try:
        import sqlite3
        from ...core.history import _get_db
        conn = sqlite3.connect(_get_db())
        conn.row_factory = sqlite3.Row
        raw_rows = conn.execute("SELECT * FROM winapp2_cleaners").fetchall()
        conn.close()
        rows = [dict(r) for r in raw_rows]
    except Exception:
        return results
    if not rows:
        return results

    # Phase 1: Pre-filter — only keep cleaners with at least one existing path
    active_cleaners = []
    for row in rows:
        try:
            fk_str = row.get("file_keys", "[]")
            file_keys = json.loads(fk_str) if isinstance(fk_str, str) else fk_str
        except Exception:
            file_keys = []
        if not file_keys:
            continue
        for fk in file_keys:
            path = fk.get("path", "")
            if path and os.path.exists(path):
                active_cleaners.append({
                    "section_name": row.get("section_name", "?"),
                    "file_keys": file_keys,
                    "category": row.get("category", "winapp2"),
                })
                break

    if not active_cleaners:
        return results

    # Phase 2: Scan active cleaners in parallel
    def _scan_one(cleaner: dict) -> list[CacheItem]:
        items = []
        section_name = cleaner["section_name"]
        for fk in cleaner["file_keys"]:
            p = fk.get("path", "")
            if not p or not os.path.exists(p):
                continue
            try:
                sz = dir_total(p) if fk.get("recurse", False) else _flat_size(p)
                if sz > 0:
                    items.append(CacheItem(
                        path=p, size=sz, provider="winapp2",
                        label=f"Winapp2: {section_name} ({os.path.basename(p)})",
                        safety=SafetyLevel.SAFE,
                        extra={"type": "winapp2", "section": section_name,
                               "rebuild_cost": "low",
                               "note": f"Imported from Winapp2.ini: {section_name}"},
                    ))
            except Exception:
                pass
        return items

    n = min(8, len(active_cleaners))
    with ThreadPoolExecutor(max_workers=n) as pool:
        futures = {pool.submit(_scan_one, c): c["section_name"] for c in active_cleaners}
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                pass
    return results


def _flat_size(path: str) -> int:
    """Sum sizes of immediate files only (no recursion)."""
    total = 0
    try:
        for e in os.scandir(path):
            if e.is_file():
                try: total += e.stat().st_size
                except Exception: pass
    except Exception:
        pass
    return total


register("winapp2", _scan_winapp2)
