"""Garbage classification rules for deep clean scanning.

Each rule can match by:
- file_glob: fnmatch pattern on filename
- extension: file extension (e.g. ".log", ".tmp")
- path_contains: substring match on full path (lowercase)
- min_age_days: only classify as garbage if older than this

Returns cleanup_confidence: 0.0-1.0
"""
import fnmatch, os, time, re

# ── Rule definitions ────────────────────────────────────

GarbageRule = dict

RULES: list[GarbageRule] = [
    # ── Build artifacts ──
    {"name": "Python cache",       "path_contains": "__pycache__",  "confidence": 0.95},
    {"name": "Python bytecode",    "file_glob": "*.pyc",            "confidence": 0.90},
    {"name": "Python pyo",         "file_glob": "*.pyo",            "confidence": 0.90},
    {"name": "Cargo build",        "path_contains": "target\\debug","confidence": 0.80},
    {"name": "Cargo build release","path_contains": "target\\release","confidence": 0.60},
    {"name": "Node modules",       "file_glob": "node_modules",     "confidence": 0.70, "min_age_days": 30},
    {"name": "TS build info",      "file_glob": "*.tsbuildinfo",    "confidence": 0.95},
    {"name": "Rust incremental",   "path_contains": "target\\incremental","confidence": 0.90},
    {"name": "Java Gradle cache",  "path_contains": ".gradle\\caches","confidence": 0.85},
    {"name": "Java Maven downloads","path_contains": ".m2\\repository","confidence": 0.70, "min_age_days": 60},
    
    # ── Cache directories ──
    {"name": "npm cache",          "path_contains": "npm-cache",    "confidence": 0.95},
    {"name": "npm _cacache",       "path_contains": "_cacache",     "confidence": 0.90},
    {"name": "pip cache",          "path_contains": "pip\\cache",   "confidence": 0.90},
    {"name": "pip wheel",          "path_contains": "pip\\wheels",  "confidence": 0.75},
    {"name": "yarn cache",         "path_contains": "\\AppData\\Local\\Yarn", "confidence": 0.90},
    {"name": "pypoetry cache",     "path_contains": "pypoetry\\cache","confidence": 0.85},
    {"name": "bun cache",          "path_contains": ".bun\\cache",  "confidence": 0.90},
    {"name": "go build cache",     "path_contains": "go\\build",    "confidence": 0.80},
    {"name": "go module cache",    "path_contains": "go\\pkg\\mod", "confidence": 0.70},
    {"name": "rustup downloads",   "path_contains": ".rustup\\downloads","confidence": 0.90},
    {"name": "cargo registry cache","path_contains": ".cargo\\registry\\cache","confidence": 0.95},
    {"name": "nuget cache",        "path_contains": "\\NuGet\\Cache","confidence": 0.90},

    # ── Browser caches ──
    {"name": "Chrome cache",       "path_contains": "\\Chrome\\User Data\\Default\\Cache", "confidence": 0.95},
    {"name": "Chrome code cache",  "path_contains": "\\Chrome\\User Data\\Default\\Code Cache", "confidence": 0.95},
    {"name": "Edge cache",         "path_contains": "\\Edge\\User Data\\Default\\Cache", "confidence": 0.95},
    {"name": "Edge code cache",    "path_contains": "\\Edge\\User Data\\Default\\Code Cache", "confidence": 0.95},
    {"name": "Firefox cache",      "path_contains": "\\Firefox\\Profiles", "confidence": 0.90},
    
    # ── Temp / logs ──
    {"name": "Windows temp",       "path_contains": "\\AppData\\Local\\Temp", "confidence": 0.90, "min_age_days": 7},
    {"name": "Windows prefetch",   "path_contains": "\\Windows\\Prefetch", "confidence": 0.70},
    {"name": "Log files",          "file_glob": "*.log",             "confidence": 0.80, "min_age_days": 30},
    {"name": "DMP crash dumps",    "file_glob": "*.dmp",             "confidence": 0.95},
    {"name": "Heap snapshots",     "file_glob": "*.heapsnapshot",    "confidence": 0.95},
    {"name": "Chrome debug log",   "file_glob": "chrome_debug.log",  "confidence": 0.90},
    {"name": "NuGet deps",         "file_glob": "project.assets.json","confidence": 0.75},
    {"name": "VS cache",           "path_contains": "\\.vs\\",       "confidence": 0.85},
    
    # ── ML/AI caches ──
    {"name": "HuggingFace cache",  "path_contains": "huggingface\\cache","confidence": 0.70},
    {"name": "Ollama blobs",       "path_contains": "ollama\\models\\blobs","confidence": 0.60},
    {"name": "Whisper cache",      "path_contains": "whisper\\cache","confidence": 0.80},

    # ── Thumbnails / icons ──
    {"name": "Thumbnail cache",    "path_contains": "\\ThumbCache",  "confidence": 0.85},
    {"name": "Icon cache",         "path_contains": "\\IconCache",   "confidence": 0.85},
    
    # ── Package manager leftovers ──
    {"name": "pip unused",         "file_glob": "pip-selfcheck.json","confidence": 0.95},
    {"name": "npm debug",          "file_glob": "npm-debug.log*",   "confidence": 0.95},
    {"name": "yarn integrity",     "file_glob": ".yarn-integrity",  "confidence": 0.90},
]


# ── Fast-path lookups (compiled at import time) ──

# Substrings that identify garbage paths (lowercase)
_GARBAGE_PATH_IN = {
    "__pycache__", "_cacache", "npm-cache", "yarn\\cache",
    "pip\\cache", "pip\\wheels", "pypoetry\\cache", ".bun\\cache",
    "go\\build", "go\\pkg\\mod", ".rustup\\downloads",
    ".cargo\\registry\\cache", "nuget\\cache",
    "\\chrome\\user data\\default\\cache",
    "\\chrome\\user data\\default\\code cache",
    "\\edge\\user data\\default\\cache",
    "\\edge\\user data\\default\\code cache",
    "\\firefox\\profiles",
    "\\appdata\\local\\temp", "\\windows\\prefetch",
    "huggingface\\cache", "ollama\\models\\blobs",
    "\\thumbcache", "\\iconcache",
    "target\\debug", "target\\release", "target\\incremental",
    ".gradle\\caches", ".m2\\repository",
    "\\.vs\\", ".git\\objects",
    "miniconda3\\pkgs",
}

# Extensions that are always garbage (if not in a protected dir)
_GARBAGE_EXTS = {".pyc", ".pyo", ".log", ".dmp", ".tmp", ".blob",
                 ".tsbuildinfo", ".heapsnapshot"}

# Fast endswith matches for known glob patterns
_GARBAGE_ENDSWITH = {
    "pip-selfcheck.json", "npm-debug.log", ".yarn-integrity",
    "chrome_debug.log", "project.assets.json",
}


def classify_file(path: str, size: int = 0, mtime: float = 0) -> tuple[str, float]:
    """Fast classification using pre-compiled lookups. ~0.5µs per file."""
    lower = path.lower()
    fname = os.path.basename(path)

    # Fast-path: check path substrings (O(len(path)))
    for sub in _GARBAGE_PATH_IN:
        if sub in lower:
            # Check age for temp files
            if "temp" in sub and mtime > 0:
                if (time.time() - mtime) < 7 * 86400:
                    continue
            return "garbage (path match)", 0.85
        if len(lower) < 100 and sub in lower:
            break  # Short path, unlikely to match further

    # Fast-path: check extension
    ext = os.path.splitext(fname)[1].lower()
    if ext in _GARBAGE_EXTS:
        # Skip .log files that are too new
        if ext == ".log" and mtime > 0:
            if (time.time() - mtime) < 30 * 86400:
                return "", 0.0
        return {
            ".pyc": ("Python bytecode", 0.95),
            ".pyo": ("Python optimized", 0.95),
            ".log": ("Log file", 0.80),
            ".dmp": ("Crash dump", 0.95),
            ".tmp": ("Temp file", 0.85),
            ".blob": ("Cache blob", 0.80),
            ".tsbuildinfo": ("TypeScript build info", 0.95),
            ".heapsnapshot": ("Heap snapshot", 0.95),
        }.get(ext, ("garbage", 0.85))

    # Slow-path: check endswith patterns
    if fname in _GARBAGE_ENDSWITH:
        return ("Package leftover", 0.90)

    return "", 0.0


def classify_dir(path: str) -> tuple[str, float]:
    """Check if the entire directory matches a garbage path.
    
    O(1) set lookup — much faster than iterating rules.
    """
    lower = path.lower()
    for sub in _GARBAGE_PATH_IN:
        if sub in lower:
            return "garbage (dir match)", 0.85
    return "", 0.0
