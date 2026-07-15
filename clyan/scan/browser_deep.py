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


def _db_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except Exception:
        return 0


def _estimate_savings(db_path: str, tables_to_clear: list[str]) -> int:
    """Estimate how many bytes can be freed by deleting rows from a SQLite DB.
    
    Uses a pragmatic method: counts pages for listed tables vs total pages.
    Actual VACUUM savings vary, but this gives a reasonable upper bound.
    """
    try:
        # If file doesn't exist, no savings
        if not os.path.isfile(db_path):
            return 0
        original_size = os.path.getsize(db_path)
        
        # Count pages in target tables
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        cur = conn.execute("PRAGMA page_count")
        total_pages = cur.fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        
        total_pages_target = 0
        for table in tables_to_clear:
            try:
                cur = conn.execute(f'SELECT COALESCE(SUM("pgsize"), 0) FROM dbstat WHERE name=?', (table,))
                row = cur.fetchone()
                if row and row[0]:
                    total_pages_target += row[0] // page_size + 1
            except Exception:
                pass
        conn.close()
        
        # Estimate: clearing target tables frees approx (target_pages/total) * file_size
        if total_pages == 0:
            return 0
        ratio = min(total_pages_target / total_pages, 0.8)  # max 80% of file
        return int(original_size * ratio)
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
    
    # Firefox
    for profile in _get_firefox_profiles():
        all_items.extend(_scan_firefox_history_savings(profile))
    
    total_size = sum(i["size"] for i in all_items)
    all_items.sort(key=lambda x: -x["size"])
    
    return {
        "total_size": total_size,
        "items": all_items,
        "chrome_profiles": len(_get_chrome_profiles()),
        "firefox_profiles": len(_get_firefox_profiles()),
    }


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
            "firefox_profiles": data["firefox_profiles"],
        }
        result.scan_time_ms = (time.time() - start) * 1000
        return result
