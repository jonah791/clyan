import os
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total





def _scan_python_caches(root: str) -> list[CacheItem]:
    results = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")

    pip_cache = os.path.join(local_appdata, "pip", "Cache")
    if os.path.isdir(pip_cache):
        sz = dir_total(pip_cache)
        if sz > 0:
            results.append(CacheItem(
                path=pip_cache, size=sz, provider="python",
                label="pip cache", safety=SafetyLevel.SAFE,
                extra={"type": "pip_cache"},
            ))

    uv_cache = os.path.join(userprofile, ".uv", "cache")
    if os.path.isdir(uv_cache):
        sz = dir_total(uv_cache)
        if sz > 0:
            results.append(CacheItem(
                path=uv_cache, size=sz, provider="python",
                label="uv cache", safety=SafetyLevel.SAFE,
                extra={"type": "uv_cache"},
            ))

    return results


register("python", _scan_python_caches)
