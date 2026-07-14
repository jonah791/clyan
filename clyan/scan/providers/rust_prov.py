import os
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total





def _scan_rust_caches(root: str) -> list[CacheItem]:
    results = []
    userprofile = os.environ.get("USERPROFILE", "")

    cargo_registry = os.path.join(userprofile, ".cargo", "registry")
    if os.path.isdir(cargo_registry):
        sz = dir_total(cargo_registry)
        if sz > 0:
            results.append(CacheItem(
                path=cargo_registry, size=sz, provider="rust",
                label="cargo registry (crates + index)",
                safety=SafetyLevel.CAUTION,
                extra={"type": "cargo_registry"},
            ))

    return results


register("rust", _scan_rust_caches)
