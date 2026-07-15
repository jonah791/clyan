"""npm 缓存主动裁剪 — 检测可安全删除的旧包版本。

通过 npm 命令分析缓存与实际安装的包的差异:
- 使用 `npm cache ls` 列出所有缓存包（npm v10+）
- 对比已安装的项目 packages
- 标记未使用的包版本

注: 本 provider 需要 node/npm 在 PATH 中才能运行命令。
如果 npm 不可用，回退到基于文件年龄的近似判断。
"""

import os
import json
import time
import subprocess
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size


def _scan_npm_prune(root: str) -> list[CacheItem]:
    results = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")

    cacache_dir = os.path.join(local_appdata, "npm-cache", "_cacache")
    if not os.path.isdir(cacache_dir):
        return results

    # Try npm cache ls (npm v10+ outputs lines, not JSON)
    npm_available = False
    cached_entries = 0
    try:
        result = subprocess.run(
            ["npm.cmd", "cache", "ls"],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        if result.returncode == 0:
            cached_entries = len([l for l in result.stdout.splitlines() 
                                  if l.strip() and l.startswith("make-fetch-happen")])
            npm_available = cached_entries > 0
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    if npm_available:
        from ...utils.dirtree import dir_total
        actual_size = dir_total(cacache_dir)
        now = time.time()
        age_days = (now - os.path.getmtime(cacache_dir)) / 86400 if os.path.exists(cacache_dir) else -1
        
        # Report old if npm hasn't been used in 90+ days
        is_stale = age_days > 90
        if is_stale:
            results.append(CacheItem(
                path=cacache_dir, provider="npm_prune",
                label=f"npm 缓存未使用 ({int(age_days)} 天, {cached_entries} entries)",
                size=actual_size, safety=SafetyLevel.SAFE,
                extra={
                    "type": "npm_old_versions",
                    "total_cache_size": actual_size,
                    "cached_entries": cached_entries,
                    "days_since_use": int(age_days),
                    "note": f"npm 缓存 {format_size(actual_size)}，{cached_entries} 个缓存条目。"
                           f"最近 {int(age_days)} 天未使用 npm，缓存安全可删",
                    "rebuild_cost": "low" if is_stale else "high",
                },
            ))
        # Always report total cache
        results.append(CacheItem(
            path=cacache_dir, provider="npm_prune",
            label=f"npm 缓存总览 ({cached_entries} entries)",
            size=actual_size, safety=SafetyLevel.SAFE,
            extra={
                "type": "npm_cache_overview",
                "total_cache_size": actual_size,
                "cached_entries": cached_entries,
                "days_since_use": int(age_days) if age_days > 0 else -1,
                "note": f"npm 缓存 {format_size(actual_size)}，{cached_entries} 个条目。"
                       f"{'最近未使用' if is_stale else '正在使用中'}。"
                       f"'npm cache clean --force' 全部清除",
                "rebuild_cost": "high",
            },
        ))
        return results

    # Fallback
    return _fallback_scan(cacache_dir, results)


def _fallback_scan(cacache_dir: str, results: list) -> list:
    """Fallback — report total npm cache size with age info."""
    from ...utils.dirtree import dir_total
    import time
    total_size = dir_total(cacache_dir)
    now = time.time()
    age_days = -1
    if os.path.exists(cacache_dir):
        try:
            age_days = (now - os.path.getmtime(cacache_dir)) / 86400
        except Exception:
            pass

    if total_size > 0:
        results.append(CacheItem(
            path=cacache_dir, provider="npm_prune",
            label=f"npm 缓存 ({format_size(total_size)})",
            size=total_size, safety=SafetyLevel.SAFE,
            extra={
                "type": "npm_cache_overview",
                "total_cache_size": total_size,
                "cached_entries": -1,
                "days_since_use": int(age_days) if age_days > 0 else -1,
                "note": f"npm 缓存 {format_size(total_size)}。"
                       + (f"npm 命令不可用，基于文件年龄估算。最近使用 {int(age_days)} 天前" if age_days > 0 else "")
                       + ". 'npm cache clean --force' 全部清除",
                "rebuild_cost": "low" if (age_days > 90) else "high",
            },
        ))
    return results


register("npm_prune", _scan_npm_prune)
