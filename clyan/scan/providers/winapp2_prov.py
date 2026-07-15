"""Winapp2 dynamic provider — scans using imported Winapp2 cleaner definitions.

Registered as a standard provider so it integrates with detect_all() and the
full scan pipeline. Lazy-loads from the clyan database.
"""

import os
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total


def _scan_winapp2(root: str) -> list[CacheItem]:
    """Scan all imported Winapp2 cleaners and return matching CacheItems."""
    results = []
    
    # Load winapp2 cleaners from DB
    try:
        import sqlite3
        from ...core.history import _get_db
        conn = sqlite3.connect(_get_db())
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM winapp2_cleaners").fetchall()
        conn.close()
    except Exception:
        return results
    
    if not rows:
        return results
    
    def _check_cleaner(row: dict) -> list[CacheItem]:
        items = []
        section_name = row["section_name"]
        file_keys_str = row.get("file_keys", "[]")
        try:
            file_keys = eval(file_keys_str) if isinstance(file_keys_str, str) else file_keys_str
        except Exception:
            file_keys = []
        
        for fk in file_keys:
            path = fk.get("path", "")
            if not path or not os.path.exists(path):
                continue
            try:
                if fk.get("recurse", False):
                    sz = dir_total(path)
                else:
                    # Non-recursive: just immediate file sizes
                    sz = 0
                    try:
                        for e in os.scandir(path):
                            if e.is_file():
                                try:
                                    sz += e.stat().st_size
                                except Exception:
                                    pass
                    except Exception:
                        pass
                if sz > 0:
                    items.append(CacheItem(
                        path=path,
                        size=sz,
                        provider="winapp2",
                        label=f"Winapp2: {section_name} ({os.path.basename(path)})",
                        safety=SafetyLevel.SAFE,
                        extra={
                            "type": "winapp2",
                            "section": section_name,
                            "rebuild_cost": "low",
                            "note": f"Imported from Winapp2.ini: {section_name}",
                        },
                    ))
            except Exception:
                pass
        return items
    
    # Process in parallel (up to 8 workers)
    with ThreadPoolExecutor(max_workers=min(8, len(rows) or 1)) as pool:
        futures = {pool.submit(_check_cleaner, dict(r)): r for r in rows}
        for f in as_completed(futures):
            try:
                results.extend(f.result())
            except Exception:
                pass
    
    return results


# Register as a standard provider
register("winapp2", _scan_winapp2)
