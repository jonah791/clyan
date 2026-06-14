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
            sz = _dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="gradle",
                    label=f"Gradle {os.path.basename(p)}",
                    safety=SafetyLevel.SAFE,
                    extra={"type": "gradle"},
                ))

    return results


register("gradle", _scan_gradle_caches)
