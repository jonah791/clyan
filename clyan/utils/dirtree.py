import os

# Simple thread-safe dir-size cache shared across a single scan session.
_cache: dict[tuple[str, int], int] = {}
_cache_lock = __import__("threading").Lock()

# Known system dirs to never recurse into (too large, too slow)
_SKIP_DIRS = {
    "$Recycle.Bin", "System Volume Information", "Recovery",
    "Windows.old", "Config.Msi", "$SysReset", "MSOCache",
    "Boot", "Documents and Settings",
}


def _reset_cache() -> None:
    global _cache
    _cache = {}


def dir_total(path: str, max_depth: int = 0) -> int:
    """Recursively sum file sizes under *path*.

    Args:
        path: Directory to sum.
        max_depth: Maximum recursion depth. 0 = unlimited (default).

    Results are cached (path, max_depth) so repeated calls return instantly.
    """
    path = os.path.normpath(path)
    if not os.path.isdir(path):
        return 0
    key = (path, max_depth)
    with _cache_lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
    total = _scan(path, max_depth)
    with _cache_lock:
        if key not in _cache:
            _cache[key] = total
    return total


def _scan(path: str, remaining: int = 0) -> int:
    """Recursive file-size sum up to *remaining* more levels.

    *remaining* = 0 means unlimited (recurse fully).
    """
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                    elif e.is_dir(follow_symlinks=False):
                        name = e.name
                        if name in _SKIP_DIRS:
                            continue
                        if remaining == 0:
                            total += _scan(e.path, 0)
                        elif remaining > 1:
                            total += _scan(e.path, remaining - 1)
                        else:
                            # remaining == 1: don't recurse into subdirs,
                            # but still count immediate files
                            total += _quick_dir_total(e.path)
                except Exception:
                    pass
    except Exception:
        pass
    return total


def _quick_dir_total(path: str) -> int:
    """Sum immediate file sizes only (no recursion)."""
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass
    return total


def reset_dir_total_cache() -> None:
    """Flush the shared cache so the next scan picks up fresh sizes."""
    _reset_cache()
