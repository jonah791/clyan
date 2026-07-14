import os
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total





def _scan_gradle_caches(root: str) -> list[CacheItem]:
    results = []
    userprofile = os.environ.get("USERPROFILE", "")

    gradle_caches = [
        os.path.join(userprofile, ".gradle", "caches"),
        os.path.join(userprofile, ".gradle", "wrapper", "dists"),
        os.path.join(userprofile, ".gradle", "daemon"),
    ]
    for p in gradle_caches:
        if os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="gradle",
                    label=f"Gradle {os.path.basename(p)}",
                    safety=SafetyLevel.SAFE,
                    extra={"type": "gradle"},
                ))

    return results


register("gradle", _scan_gradle_caches)
