import os
import shutil
from datetime import datetime, timezone


def get_age_days(path: str) -> int | None:
    """Return days since last modification of *path*.

    For directories, walks up to 1000 entries to find the newest mtime
    (capped for performance on huge dirs).  Returns ``None`` on error.
    """
    try:
        if os.path.isfile(path):
            mtime = os.path.getmtime(path)
            return _days_since(mtime)

        if os.path.isdir(path):
            newest = 0.0
            count = 0
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        st = entry.stat()
                        if st.st_mtime > newest:
                            newest = st.st_mtime
                    except Exception:
                        pass
                    count += 1
                    if count >= 1000:
                        break
            if newest > 0:
                return _days_since(newest)

        return None
    except Exception:
        return None


def _days_since(timestamp: float) -> int:
    now = datetime.now(timezone.utc).timestamp()
    diff = now - timestamp
    return max(0, int(diff // 86400))


def is_tool_installed(tool: str) -> bool:
    """Check whether *tool* is available on PATH."""
    return shutil.which(tool) is not None


# ── Orphan helpers: cross-reference package-manager caches with installed tools ──

_TOOL_MAP: dict[str, list[str]] = {
    "npm_cache": ["npm", "node"],
    "python": ["python", "python3", "pip", "pip3"],
    "rust": ["rustc", "cargo"],
    "go": ["go"],
    "gradle": ["gradle"],
    "nuget": ["dotnet"],
    "android": ["adb", "gradle"],
    "flutter": ["dart", "flutter"],
    "docker": ["docker"],
}


def cache_type_installed(cache_type: str) -> bool:
    """Return True if at least one tool for *cache_type* is on PATH."""
    tools = _TOOL_MAP.get(cache_type)
    if not tools:
        return True  # unknown type → assume safe
    return any(is_tool_installed(t) for t in tools)
