import os

# Simple thread-safe dir-size cache shared across a single scan session.
# The global lock is fine because cache lookups are cheap and we never
# hold it during I/O (computation happens outside the lock).
_cache: dict[str, int] = {}
_cache_lock = __import__("threading").Lock()


def _reset_cache() -> None:
    global _cache
    _cache = {}


def dir_total(path: str) -> int:
    """Recursively sum file sizes under *path*.

    Results are cached in a thread-safe dict so repeated calls for
    the same directory within a scan session return instantly.
    """
    path = os.path.normpath(path)

    with _cache_lock:
        cached = _cache.get(path)
        if cached is not None:
            return cached

    total = _scan(path)

    with _cache_lock:
        if path not in _cache:
            _cache[path] = total
    return total


def _scan(path: str) -> int:
    """Single-threaded recursive file-size sum — no pool nesting."""
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                    elif e.is_dir(follow_symlinks=False):
                        total += dir_total(e.path)
                except Exception:
                    pass
    except Exception:
        pass
    return total


def reset_dir_total_cache() -> None:
    """Flush the shared cache so the next scan picks up fresh sizes."""
    _reset_cache()
