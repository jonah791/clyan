"""Browser deep cleaner — Chrome/Firefox history, autofill, favicons.

Unlike the directory-level browser cache scanner, this module operates on
SQLite databases inside browser profiles to selectively clear data while
preserving bookmarks and whitelisted cookies.

Inspired by BleachBit's specialized browser cleaners.
"""

import os
import time
import sqlite3
from ..utils.scanner_base import ScanResult, BaseScanner
from ..utils.size import format_size


def _get_chrome_profiles() -> list[str]:
    """Find all Chrome profile directories."""
    profiles = []
    local = os.environ.get("LOCALAPPDATA", "")
    base = os.path.join(local, "Google", "Chrome", "User Data")
    if not os.path.isdir(base):
        return profiles
    # Default profile
    default = os.path.join(base, "Default")
    if os.path.isdir(default):
        profiles.append(default)
    # Named profiles (Profile 1, Profile 2, ...)
    for name in os.listdir(base):
        if name.startswith("Profile "):
            p = os.path.join(base, name)
            if os.path.isdir(p):
                profiles.append(p)
    return profiles


def _get_firefox_profiles() -> list[str]:
    """Find all Firefox profile directories."""
    profiles = []
    appdata = os.environ.get("APPDATA", "")
    base = os.path.join(appdata, "Mozilla", "Firefox", "Profiles")
    if not os.path.isdir(base):
        return profiles
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if os.path.isdir(p):
            profiles.append(p)
    return profiles


def _get_edge_profiles() -> list[str]:
    """Find all Edge profile directories."""
    profiles = []
    local = os.environ.get("LOCALAPPDATA", "")
    base = os.path.join(local, "Microsoft", "Edge", "User Data")
    if not os.path.isdir(base):
        return profiles
    default = os.path.join(base, "Default")
    if os.path.isdir(default):
        profiles.append(default)
    for name in os.listdir(base):
        if name.startswith("Profile "):
            p = os.path.join(base, name)
            if os.path.isdir(p):
                profiles.append(p)
    return profiles


def _db_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def _estimate_savings(db_path: str, tables_to_clear: list[str]) -> int:
    """Quick estimate: fraction of file size based on target/table count ratio.
    Avoids COUNT(*) on large tables to prevent slow queries."""
    try:
        if not os.path.isfile(db_path):
            return 0
        file_size = os.path.getsize(db_path)
        if file_size < 4096:
            return 0

        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        conn.execute("PRAGMA query_only = 1")
        conn.execute("PRAGMA busy_timeout = 2000")
        
        # Get all user table names
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        all_tables = [row[0] for row in cur.fetchall()]
        conn.close()
        
        if not all_tables:
            return 0
        
        # Ratio = target tables / total tables (quick, no row counting)
        target_count = sum(1 for t in tables_to_clear if t in all_tables)
        if target_count == 0:
            return 0
        ratio = min(target_count / len(all_tables), 0.8)
        return int(file_size * ratio)
    except Exception:
        return 0


def _scan_chrome_history_savings(profile: str) -> list[dict]:
    """Estimate savings from clearing Chrome history (keeps bookmarks)."""
    results = []
    history_db = os.path.join(profile, "History")
    if not os.path.isfile(history_db):
        return results
    
    # Chrome History tables: visits and urls (keeps bookmarked URLs)
    savings = _estimate_savings(history_db, ["visits", "urls", "keyword_search_terms", "downloads", "segments", "segment_usage"])
    if savings > 0:
        results.append({
            "path": history_db,
            "size": savings,
            "db_path": history_db,
            "label": f"Chrome History ({os.path.basename(profile)})",
            "type": "chrome_history",
            "note": "Clears history, keeps bookmarks",
        })
    
    # Web Data: autofill
    web_db = os.path.join(profile, "Web Data")
    if os.path.isfile(web_db):
        savings_af = _estimate_savings(web_db, ["autofill", "autofill_entry", "autofill_profile", "autofill_profile_addresses"])
        if savings_af > 0:
            results.append({
                "path": web_db,
                "size": savings_af,
                "db_path": web_db,
                "label": f"Chrome Autofill ({os.path.basename(profile)})",
                "type": "chrome_autofill",
                "note": "Clears autofill entries",
            })
    
    # Favicons (keep bookmarked ones)
    fav_db = os.path.join(profile, "Favicons")
    if os.path.isfile(fav_db):
        savings_fav = _estimate_savings(fav_db, ["favicons", "favicon_bitmaps"])
        if savings_fav > 0:
            results.append({
                "path": fav_db,
                "size": savings_fav,
                "db_path": fav_db,
                "label": f"Chrome Favicons ({os.path.basename(profile)})",
                "type": "chrome_favicons",
                "note": "Clears non-bookmarked favicons",
            })
    
    return results


def _scan_firefox_history_savings(profile: str) -> list[dict]:
    """Estimate savings from clearing Firefox history (keeps bookmarks)."""
    results = []
    places_db = os.path.join(profile, "places.sqlite")
    if not os.path.isfile(places_db):
        return results
    
    # Firefox places.sqlite: moz_historyvisits, moz_places, moz_annos (keeps bookmarked URLs)
    savings = _estimate_savings(places_db, ["moz_historyvisits", "moz_places", "moz_annos", "moz_inputhistory", "moz_hosts"])
    if savings > 0:
        results.append({
            "path": places_db,
            "size": savings,
            "db_path": places_db,
            "label": f"Firefox History ({os.path.basename(profile)})",
            "type": "firefox_history",
            "note": "Clears history, keeps bookmarks",
        })
    
    # Favicons
    fav_db = os.path.join(profile, "favicons.sqlite")
    if os.path.isfile(fav_db):
        savings_fav = _estimate_savings(fav_db, ["moz_icons", "moz_icons_to_pages"])
        if savings_fav > 0:
            results.append({
                "path": fav_db,
                "size": savings_fav,
                "db_path": fav_db,
                "label": f"Firefox Favicons ({os.path.basename(profile)})",
                "type": "firefox_favicons",
                "note": "Clears non-bookmarked favicons",
            })
    
    return results


def scan_browser_deep() -> dict:
    """Scan Chrome and Firefox profiles for deep-cleanable browser data."""
    all_items = []
    
    # Chrome
    for profile in _get_chrome_profiles():
        all_items.extend(_scan_chrome_history_savings(profile))
        all_items.extend(_scan_profile_cache_dirs(profile, "Chrome"))
    
    # Edge (same Chromium internals as Chrome)
    for profile in _get_edge_profiles():
        items = _scan_chrome_history_savings(profile)
        for item in items:
            item["label"] = item["label"].replace("Chrome", "Edge")
            item["type"] = item["type"].replace("chrome", "edge")
        all_items.extend(items)
        all_items.extend(_scan_profile_cache_dirs(profile, "Edge"))
    
    # Firefox
    for profile in _get_firefox_profiles():
        all_items.extend(_scan_firefox_history_savings(profile))
    
    total_size = sum(i["size"] for i in all_items)
    all_items.sort(key=lambda x: -x["size"])
    
    return {
        "total_size": total_size,
        "items": all_items,
        "chrome_profiles": len(_get_chrome_profiles()),
        "edge_profiles": len(_get_edge_profiles()),
        "firefox_profiles": len(_get_firefox_profiles()),
    }


def _scan_profile_cache_dirs(profile_dir: str, browser: str) -> list[dict]:
    """Scan a Chromium profile for additional cleanable cache directories.
    
    Targets: Service Worker cache, IndexedDB, FileSystem, Extension caches.
    These are standard Chromium subdirectories that can grow large.
    """
    from ..utils.dirtree import dir_total
    results = []
    
    # Service Worker cache
    sw_cache = os.path.join(profile_dir, "Service Worker", "CacheStorage")
    if os.path.isdir(sw_cache):
        sz = dir_total(sw_cache)
        if sz > 1_000_000:
            results.append({
                "path": sw_cache,
                "size": sz,
                "db_path": sw_cache,
                "label": f"{browser} Service Worker 缓存 ({format_size(sz)})",
                "type": f"{browser.lower()}_sw_cache",
                "note": "Service Worker 缓存，清除后网站需重新注册 Service Worker",
                "provider": "browser_deep",
            })
    
    # IndexedDB
    idb = os.path.join(profile_dir, "IndexedDB")
    if os.path.isdir(idb):
        sz = dir_total(idb)
        if sz > 1_000_000:
            results.append({
                "path": idb,
                "size": sz,
                "db_path": idb,
                "label": f"{browser} IndexedDB ({format_size(sz)})",
                "type": f"{browser.lower()}_indexeddb",
                "note": "IndexedDB 数据，清除后网站本地数据丢失",
                "provider": "browser_deep",
            })
    
    # FileSystem (persistent storage)
    fs = os.path.join(profile_dir, "File System")
    if os.path.isdir(fs):
        sz = dir_total(fs)
        if sz > 1_000_000:
            results.append({
                "path": fs,
                "size": sz,
                "db_path": fs,
                "label": f"{browser} FileSystem 存储 ({format_size(sz)})",
                "type": f"{browser.lower()}_filesystem",
                "note": "浏览器持久化存储，清除后网站存储数据丢失",
                "provider": "browser_deep",
            })
    
    # Extension caches
    ext_cache = os.path.join(profile_dir, "Extension State")
    if os.path.isdir(ext_cache):
        sz = dir_total(ext_cache)
        if sz > 1_000_000:
            results.append({
                "path": ext_cache,
                "size": sz,
                "db_path": ext_cache,
                "label": f"{browser} 扩展缓存 ({format_size(sz)})",
                "type": f"{browser.lower()}_ext_state",
                "note": "浏览器扩展持久化状态，清除后扩展可能需重新登录",
                "provider": "browser_deep",
            })
    
    # Session Storage
    ss = os.path.join(profile_dir, "Session Storage")
    if os.path.isdir(ss):
        sz = dir_total(ss)
        if sz > 1_000_000:
            results.append({
                "path": ss,
                "size": sz,
                "db_path": ss,
                "label": f"{browser} Session 存储 ({format_size(sz)})",
                "type": f"{browser.lower()}_session_store",
                "note": "浏览器会话存储，清除后关闭的标签页状态丢失",
                "provider": "browser_deep",
            })
    
    # Local Storage / WebSQL
    ls = os.path.join(profile_dir, "Local Storage")
    if os.path.isdir(ls):
        sz = dir_total(ls)
        if sz > 5_000_000:  # 5 MB threshold for localStorage
            results.append({
                "path": ls,
                "size": sz,
                "db_path": ls,
                "label": f"{browser} LocalStorage ({format_size(sz)})",
                "type": f"{browser.lower()}_local_storage",
                "note": "浏览器本地存储，清除后网站偏好设置丢失",
                "provider": "browser_deep",
            })
    
    return results


class BrowserDeepScanner(BaseScanner):
    """Deep browser data scanner — estimates reclaimable space from
    history/autofill/favicons SQLite databases without deleting bookmarks."""

    def __init__(self):
        pass

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        data = scan_browser_deep()

        for item in data["items"]:
            result.items.append({
                "path": item["path"],
                "size": item["size"],
                "size_human": format_size(item["size"]),
                "provider": "browser_deep",
                "safety": "safe",
                "label": item["label"],
                "extra": {
                    "type": item["type"],
                    "db_path": item["db_path"],
                    "rebuild_cost": "none",
                    "note": item["note"],
                },
            })
            result.total_size += item["size"]

        result.item_count = len(data["items"])
        result.extra = {
            "chrome_profiles": data["chrome_profiles"],
            "edge_profiles": data["edge_profiles"],
            "firefox_profiles": data["firefox_profiles"],
        }
        result.scan_time_ms = (time.time() - start) * 1000
        return result
