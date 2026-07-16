"""空目录扫描 — 安全删除不包含任何文件的空目录。

Czkawka-style: 扫描用户目录下所有空目录。
只删除 >90 天空且非系统关键路径的空目录。
"""

import os
import time
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size
from ...utils.scanner_base import safe_walk
from ...core.config import is_protected

# 跳过的目录名
_SKIP_EMPTY = {
    "Windows", "Program Files", "Program Files (x86)",
    "System32", "SysWOW64", "WinSxS", "assembly",
    "node_modules", ".git", ".svn", ".hg",
    "AppData", "Application Data",
    "$Recycle.Bin", "System Volume Information",
    "Recovery", "ProgramData",
}


def _scan_empty_dirs(root: str) -> list[CacheItem]:
    results = []
    now = time.time()
    empty_dirs = []
    total_size = 0  # directory entries have 0 size but we count them

    try:
        for dirpath, dirs, files in safe_walk(root, max_depth=6):
            # Skip system dirs
            parts = dirpath.split(os.sep)
            skip = False
            for s in _SKIP_EMPTY:
                if s in parts:
                    skip = True
                    break
            if skip:
                dirs.clear()
                continue

            # A directory is empty if it has no files and no subdirectories
            effective_dirs = [d for d in dirs if not d.startswith(".")]
            if not files and not effective_dirs:
                try:
                    mtime = os.path.getmtime(dirpath)
                    age = (now - mtime) / 86400
                    if age > 90:
                        empty_dirs.append({"path": dirpath, "age": int(age)})
                except (OSError, PermissionError):
                    pass
    except Exception:
        pass

    if not empty_dirs:
        return results

    # Filter out protected directories
    empty_dirs = [ed for ed in empty_dirs if not is_protected(ed["path"])]
    if not empty_dirs:
        return results

    # Group by parent directory
    from collections import defaultdict
    by_parent: dict[str, list[dict]] = defaultdict(list)
    for ed in empty_dirs:
        parent = os.path.dirname(ed["path"])
        by_parent[parent].append(ed)

    # For each parent, create an item
    for parent, children in sorted(by_parent.items(), key=lambda x: -len(x[1])):
        if len(children) == 1:
            ed = children[0]
            results.append(CacheItem(
                path=ed["path"], size=0,
                provider="empty_dirs",
                label=f"空目录: {os.path.basename(ed['path'])} ({ed['age']} 天未用)",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "empty_dir_single",
                    "age_days": ed["age"],
                    "note": f"空目录，{ed['age']} 天未使用。安全可删",
                    "rebuild_cost": "none",
                },
            ))
        else:
            # Group multiple empty dirs under same parent
            paths = [c["path"] for c in children]
            results.append(CacheItem(
                path=parent, size=0,
                provider="empty_dirs",
                label=f"空目录 ({len(children)} 个, {min(c['age'] for c in children)}-{max(c['age'] for c in children)} 天)",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "empty_dir_group",
                    "dir_count": len(children),
                    "sample_paths": paths[:10],
                    "min_age": min(c["age"] for c in children),
                    "max_age": max(c["age"] for c in children),
                    "note": f"{len(children)} 个空目录，{min(c['age'] for c in children)}-{max(c['age'] for c in children)} 天未使用。安全可删",
                    "rebuild_cost": "none",
                },
            ))

    return results


register("empty_dirs", _scan_empty_dirs)
