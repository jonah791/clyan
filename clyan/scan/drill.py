"""Progressive drill-down scanner — clyan scan [path]

Usage:
    clyan scan           # C:/ top-level overview (3s)
    clyan scan <path>    # drill into that directory
    
    # Special:
    clyan scan .         # current dir
    clyan scan >         # largest subdirectory of C:/
"""
import os
import time
import json
from pathlib import Path

# Cache: dirpath -> {timestamp, items, total_size, inaccessible}
_SCAN_CACHE: dict[str, dict] = {}
_CACHE_TTL = 300  # 5 minutes


def _get_cache(path: str) -> dict | None:
    """Return cached result if fresh."""
    norm = Path(path).as_posix()
    cached = _SCAN_CACHE.get(norm)
    if cached and time.time() - cached["_ts"] < _CACHE_TTL:
        return cached
    return None


def _set_cache(path: str, data: dict) -> None:
    norm = Path(path).as_posix()
    data["_ts"] = time.time()
    _SCAN_CACHE[norm] = data
    # Keep cache small
    if len(_SCAN_CACHE) > 50:
        oldest = min(_SCAN_CACHE.keys(), key=lambda k: _SCAN_CACHE[k].get("_ts", 0))
        del _SCAN_CACHE[oldest]


def scan_dir(path: str) -> dict:
    """Scan a directory and return structured results.
    
    Returns:
        path: scanned path
        total_size: recursive total of direct children
        total_size_human: formatted
        items: list of {name, path, size, size_human, is_dir, depth}
        inaccessible: AccessTracker report
        cached: whether result is from cache
    """
    cached = _get_cache(path)
    if cached:
        result = dict(cached)
        result["cached"] = True
        return result

    path_obj = Path(path)
    if not path_obj.exists():
        return {"error": f"path not found: {path}", "path": path}
    if not path_obj.is_dir():
        sz = path_obj.stat().st_size
        return {
            "path": path,
            "is_file": True,
            "size": sz,
            "size_human": _fmt(sz),
        }

    from ..utils.tracker import AccessTracker
    tracker = AccessTracker()

    items = []
    total = 0
    max_depth = 3  # how deep to recurse

    try:
        for entry in os.scandir(str(path_obj)):
            if entry.name.startswith("$"):
                continue
            sz = 0
            is_dir = entry.is_dir()
            try:
                if is_dir:
                    for r, dirs, files in os.walk(entry.path, topdown=True):
                        depth = r.replace(str(path_obj), "").count(os.sep)
                        if depth >= max_depth:
                            dirs.clear()
                        for f in files:
                            try: sz += os.path.getsize(os.path.join(r, f))
                            except: tracker.record(os.path.join(r, f), "access denied")
                else:
                    sz = entry.stat().st_size
            except PermissionError:
                tracker.record(entry.path, "permission denied")
                continue
            except Exception:
                continue

            total += sz
            items.append({
                "name": entry.name,
                "path": entry.path,
                "size": sz,
                "size_human": _fmt(sz),
                "is_dir": is_dir,
                "has_subdirs": is_dir and _has_subdirs(entry.path),
            })
    except PermissionError:
        tracker.record(path, "permission denied")

    items.sort(key=lambda x: -x["size"])

    # Mark largest dir with >
    if items:
        items[0]["largest"] = True

    result = {
        "path": str(path_obj.resolve()),
        "total_size": total,
        "total_size_human": _fmt(total),
        "item_count": len(items),
        "items": items[:50],  # limit to top 50
        "inaccessible": tracker.report(),
        "cached": False,
    }

    _set_cache(path, result)
    return result


def _has_subdirs(path: str) -> bool:
    """Quick check if a directory has subdirectories."""
    try:
        for entry in os.scandir(path):
            if entry.is_dir():
                return True
    except:
        pass
    return False


def _fmt(size: int) -> str:
    if size > 1e9: return f"{size/1e9:.2f} GB"
    if size > 1e6: return f"{size/1e6:.1f} MB"
    if size > 1e3: return f"{size/1e3:.0f} KB"
    return f"{size} B"
