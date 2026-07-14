import os
import glob
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total


def _scan_maven(root: str) -> list[CacheItem]:
    """Maven local repository — downloaded dependency jars, can be GBs."""
    results = []
    home = os.environ.get("USERPROFILE", "")
    repo = os.path.join(home, ".m2", "repository")
    if os.path.isdir(repo):
        sz = dir_total(repo)
        if sz > 0:
            results.append(CacheItem(
                path=repo, size=sz, provider="maven_cache",
                label="Maven local repository (dependencies)",
                safety=SafetyLevel.CAUTION,
                extra={"type": "maven_repo", "rebuild_cost": "high"},
            ))
    return results


register("maven", _scan_maven)
