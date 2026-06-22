import os
from . import CacheItem, SafetyLevel, register


def _dir_total(path: str) -> int:
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                    elif e.is_dir(follow_symlinks=False):
                        total += _dir_total(e.path)
                except Exception:
                    pass
    except Exception:
        pass
    return total


def _scan_rust_caches(root: str) -> list[CacheItem]:
    results = []
    userprofile = os.environ.get("USERPROFILE", "")

    cargo_registry = os.path.join(userprofile, ".cargo", "registry")
    if os.path.isdir(cargo_registry):
        sz = _dir_total(cargo_registry)
        if sz > 0:
            results.append(CacheItem(
                path=cargo_registry, size=sz, provider="rust",
                label="cargo registry (crates + index)",
                safety=SafetyLevel.CAUTION,
                extra={"type": "cargo_registry"},
            ))

    return results


register("rust", _scan_rust_caches)
