"""Winapp2.ini parser and importer.

Winapp2.ini is the community-maintained cleaner definition format used by
CCleaner and BleachBit. Contains 2400+ cleaner definitions for Windows apps.

Format:
    [Cleaner Name]
    LangSecRef=Category
    Detect=HKCU\Software\App
    DetectFile=%ProgramFiles%\App\app.exe
    Default=True
    FileKey1=%APPDATA%\App\Cache|*.*|RECURSE
    FileKey2=%LOCALAPPDATA%\App\Temp|*.tmp
    RegKey1=HKCU\Software\App\MRU
"""

import os
import re
import sqlite3
import datetime
from pathlib import Path
from typing import Optional
from ..core.history import _get_db, _conn


# ── Winapp2 cleaner table ──

def _ensure_table():
    conn = sqlite3.connect(_get_db())
    conn.execute("""
        CREATE TABLE IF NOT EXISTS winapp2_cleaners (
            section_name TEXT PRIMARY KEY,
            lang_sec_ref TEXT DEFAULT '',
            detect TEXT DEFAULT '',
            detect_file TEXT DEFAULT '',
            is_default INTEGER DEFAULT 1,
            file_keys TEXT DEFAULT '[]',
            reg_keys TEXT DEFAULT '[]',
            category TEXT DEFAULT '',
            imported_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ── INI Parser ──

_APP_VARS = {
    "%AppData%": "APPDATA",
    "%LocalAppData%": "LOCALAPPDATA",
    "%ProgramFiles%": "ProgramFiles",
    "%ProgramFilesX86%": "ProgramFiles(x86)",
    "%WinDir%": "WINDIR",
    "%UserProfile%": "USERPROFILE",
    "%SystemDrive%": "SystemDrive",
    "%AllUsersProfile%": "ALLUSERSPROFILE",
    "%Public%": "PUBLIC",
    "%Temp%": "TEMP",
}

# Known relative paths for common roots
_ROOT_MAP = {
    "APPDATA": lambda: os.environ.get("APPDATA", ""),
    "LOCALAPPDATA": lambda: os.environ.get("LOCALAPPDATA", ""),
    "ProgramFiles": lambda: os.environ.get("ProgramFiles", "C:\\Program Files"),
    "ProgramFiles(x86)": lambda: os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)"),
    "WINDIR": lambda: os.environ.get("WINDIR", "C:\\Windows"),
    "USERPROFILE": lambda: os.environ.get("USERPROFILE", "C:\\Users\\default"),
    "SystemDrive": lambda: "C:",
    "ALLUSERSPROFILE": lambda: os.environ.get("ALLUSERSPROFILE", "C:\\ProgramData"),
    "PUBLIC": lambda: os.environ.get("PUBLIC", "C:\\Users\\Public"),
    "TEMP": lambda: os.environ.get("TEMP", os.environ.get("TMP", "")),
}

_CATEGORY_MAP = {
    "Applications": "app_cache",
    "Internet": "browser_cache",
    "Multimedia": "app_cache",
    "Office": "app_cache",
    "System": "windows_system",
    "Utilities": "app_cache",
    "Development": "build_artifacts",
    "Games": "app_cache",
    "Security": "app_cache",
    "Accessories": "app_cache",
}


def _resolve_path(winapp_path: str) -> Optional[str]:
    """Resolve a Winapp2-style path with %VAR% to a real Windows path."""
    result = winapp_path
    for var, env_key in _APP_VARS.items():
        if var in result:
            resolved = _ROOT_MAP.get(env_key, lambda: "")()
            if not resolved:
                return None
            result = result.replace(var, resolved)
    # Normalize
    result = os.path.normpath(result)
    return result


def _parse_file_key(value: str) -> Optional[dict]:
    """Parse a FileKey value like '%APPDATA%\\App\\Cache|*.*|RECURSE'"""
    if "|" not in value:
        return None
    parts = value.split("|")
    path_part = parts[0].strip()
    filemask = parts[1].strip() if len(parts) > 1 else "*.*"
    options = parts[2].strip().upper() if len(parts) > 2 else ""
    
    path = _resolve_path(path_part)
    if not path:
        return None
    
    return {
        "path": path,
        "filemask": filemask,
        "recurse": "RECURSE" in options,
        "removedsn": "REMOVEDSN" in options or "REMOVESELF" in options,
    }


def _parse_reg_key(value: str) -> Optional[dict]:
    """Parse a RegKey value like 'HKCU\\Software\\App\\MRU'"""
    value = value.strip()
    if not value:
        return None
    parts = value.split("|")
    key = parts[0].strip()
    return {"key": key, "value": parts[1].strip() if len(parts) > 1 else ""}


def _categorize(section: dict) -> str:
    """Determine clyan provider category from LangSecRef."""
    lsr = section.get("lang_sec_ref", "")
    return _CATEGORY_MAP.get(lsr, "winapp2")


def parse_winapp2_ini(content: str) -> list[dict]:
    """Parse Winapp2.ini content into structured cleaner definitions.
    Returns list of {section_name, lang_sec_ref, detect, detect_file,
                      is_default, file_keys, reg_keys, category}
    """
    sections = []
    current: Optional[dict] = None
    
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(";"):
            continue
        
        # Section header
        if line.startswith("[") and line.endswith("]"):
            if current and current.get("file_keys"):
                current["category"] = _categorize(current)
                sections.append(current)
            current = {
                "section_name": line[1:-1].strip(),
                "lang_sec_ref": "",
                "detect": "",
                "detect_file": "",
                "is_default": True,
                "file_keys": [],
                "reg_keys": [],
                "category": "",
            }
            continue
        
        if current is None:
            continue
        
        # Key=Value
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        
        if key == "LangSecRef":
            current["lang_sec_ref"] = value
        elif key == "Detect":
            current["detect"] = value
        elif key == "DetectFile":
            current["detect_file"] = value
        elif key == "DetectOS":
            # Only support Windows (all winapp2 cleaners are Windows)
            current["detect_os"] = value
        elif key == "Default":
            current["is_default"] = value.lower() in ("true", "1", "yes")
        elif key.startswith("FileKey"):
            parsed = _parse_file_key(value)
            if parsed:
                current["file_keys"].append(parsed)
        elif key.startswith("RegKey"):
            parsed = _parse_reg_key(value)
            if parsed:
                current["reg_keys"].append(parsed)
    
    # Don't forget the last section
    if current and current.get("file_keys"):
        current["category"] = _categorize(current)
        sections.append(current)
    
    return sections


def import_winapp2(content: str) -> dict:
    """Parse Winapp2.ini content and store in the clyan database.
    
    Returns: {"imported": N, "sections": N, "file_keys": N, "reg_keys": N}
    """
    _ensure_table()
    sections = parse_winapp2_ini(content)
    conn = sqlite3.connect(_get_db())
    now = datetime.datetime.now().isoformat()
    
    imported = 0
    total_file_keys = 0
    total_reg_keys = 0
    
    for sec in sections:
        file_keys_json = str(sec.get("file_keys", []))
        reg_keys_json = str(sec.get("reg_keys", []))
        total_file_keys += len(sec.get("file_keys", []))
        total_reg_keys += len(sec.get("reg_keys", []))
        
        try:
            conn.execute(
                """INSERT OR REPLACE INTO winapp2_cleaners
                   (section_name, lang_sec_ref, detect, detect_file, is_default,
                    file_keys, reg_keys, category, imported_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    sec["section_name"],
                    sec.get("lang_sec_ref", ""),
                    sec.get("detect", ""),
                    sec.get("detect_file", ""),
                    1 if sec.get("is_default", True) else 0,
                    file_keys_json,
                    reg_keys_json,
                    sec.get("category", ""),
                    now,
                ),
            )
            imported += 1
        except Exception as e:
            pass
    
    conn.commit()
    conn.close()
    
    return {
        "imported": imported,
        "total_sections": len(sections),
        "total_file_keys": total_file_keys,
        "total_reg_keys": total_reg_keys,
    }


def get_winapp2_cleaners(category: str = "", limit: int = 100) -> list[dict]:
    """Query imported Winapp2 cleaners from DB."""
    conn = sqlite3.connect(_get_db())
    conn.row_factory = sqlite3.Row
    if category:
        rows = conn.execute(
            "SELECT * FROM winapp2_cleaners WHERE category = ? ORDER BY section_name LIMIT ?",
            (category, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM winapp2_cleaners ORDER BY section_name LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_winapp2_stats() -> dict:
    """Return import statistics."""
    conn = sqlite3.connect(_get_db())
    count = conn.execute("SELECT COUNT(*) FROM winapp2_cleaners").fetchone()[0]
    categories = conn.execute(
        "SELECT category, COUNT(*) as cnt FROM winapp2_cleaners GROUP BY category ORDER BY cnt DESC"
    ).fetchall()
    conn.close()
    return {
        "total_imported": count,
        "categories": [{"category": r[0] or "other", "count": r[1]} for r in categories],
    }


def detect_installed(detect: str, detect_file: str) -> bool:
    """Check if an app is installed by Detect (registry) or DetectFile (file)."""
    if detect_file:
        path = _resolve_path(detect_file)
        if path and os.path.exists(path):
            return True
    if detect:
        # Simple registry check via REG QUERY
        try:
            import subprocess
            r = subprocess.run(
                ["reg", "query", detect],
                capture_output=True, timeout=5,
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
            return r.returncode == 0
        except Exception:
            pass
    return False
