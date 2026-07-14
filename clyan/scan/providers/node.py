import os
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total





def _scan_node_caches(root: str) -> list[CacheItem]:
    results = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")

    npm_cache = os.path.join(local_appdata, "npm-cache")
    if os.path.isdir(npm_cache):
        sz = dir_total(npm_cache)
        if sz > 0:
            results.append(CacheItem(
                path=npm_cache, size=sz, provider="npm_cache",
                label="npm global cache", safety=SafetyLevel.SAFE,
                extra={"type": "npm_cache"},
            ))

    pnpm_store = os.path.join(local_appdata, "pnpm", "store")
    if os.path.isdir(pnpm_store):
        sz = dir_total(pnpm_store)
        if sz > 0:
            results.append(CacheItem(
                path=pnpm_store, size=sz, provider="npm_cache",
                label="pnpm store", safety=SafetyLevel.SAFE,
                extra={"type": "pnpm_store"},
            ))

    bun_dir = os.path.join(userprofile, ".bun")
    if os.path.isdir(bun_dir):
        sz = dir_total(bun_dir)
        if sz > 0:
            results.append(CacheItem(
                path=bun_dir, size=sz, provider="bun_cache",
                label="bun cache & install", safety=SafetyLevel.SAFE,
                extra={"type": "bun_cache"},
            ))

    return results


register("npm_cache", _scan_node_caches)
