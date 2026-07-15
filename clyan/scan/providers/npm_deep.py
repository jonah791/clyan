"""npm 缓存深度扫描 — 按子组件分解，AI 选择性清理。

npm 缓存不是铁板一块的。不同子目录有不同的清理安全性和重建成本:
  - _npx/: npx 下载的一次性二进制（运行完就无用）→ SAFE, cost=none
  - _cacache/: 按版本存储的压缩包，旧版本可删 → SAFE, cost=low 到 high
  - node_modules/: 全局安装的包 → SAFE to remove all, cost=high

本 provider 拆解这些子组件并附加年龄/访问时间信号。
"""

import os
import time
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total
from ...utils.size import format_size


def _scan_npm_deep(root: str) -> list[CacheItem]:
    results = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")

    npm_cache_dir = os.path.join(local_appdata, "npm-cache")
    if not os.path.isdir(npm_cache_dir):
        return results

    # ── 1. _npx/ — npx 单次二进制 ──
    npx_dir = os.path.join(npm_cache_dir, "_npx")
    if os.path.isdir(npx_dir):
        sz = dir_total(npx_dir)
        if sz > 0:
            # _npx 下每个目录是一个包的二进制，记录个数
            try:
                bin_count = len([d for d in os.listdir(npx_dir)
                                 if os.path.isdir(os.path.join(npx_dir, d))])
            except Exception:
                bin_count = 0

            # 检查最后访问时间（取子目录 mtime 最大值）
            try:
                newest = max(
                    os.path.getmtime(os.path.join(npx_dir, d))
                    for d in os.listdir(npx_dir)
                    if os.path.isdir(os.path.join(npx_dir, d))
                )
                age_days = max(0, (time.time() - newest) / 86400)
            except Exception:
                age_days = -1

            label = "npx 已下载二进制"
            if bin_count > 0:
                label += f" ({bin_count} packages)"
            note = "一次性 npx 二进制，运行完后无需保留"
            if age_days >= 0:
                note += f"，最近使用 {int(age_days)} 天前"

            results.append(CacheItem(
                path=npx_dir,
                size=sz,
                provider="npm_deep",
                label=label,
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "npx_cache",
                    "bin_count": bin_count,
                    "age_days_approx": int(age_days),
                    "note": note,
                    "rebuild_cost": "none",
                },
            ))

    # ── 2. _cacache/ — 内容寻址缓存 ──
    cacache_dir = os.path.join(npm_cache_dir, "_cacache")
    if os.path.isdir(cacache_dir):
        sz = dir_total(cacache_dir)
        if sz > 0:
            # 按年份分组统计（目录 mtime）
            try:
                year_sizes = {}
                for entry in os.listdir(cacache_dir):
                    ep = os.path.join(cacache_dir, entry)
                    if os.path.isdir(ep):
                        try:
                            mtime = os.path.getmtime(ep)
                            year = time.strftime("%Y", time.localtime(mtime))
                            year_sizes[year] = year_sizes.get(year, 0) + dir_total(ep)
                        except Exception:
                            year_sizes.setdefault("unknown", 0)
                            year_sizes["unknown"] += dir_total(ep)
            except Exception:
                year_sizes = {}

            # 估算老旧版本占比
            total_old = sum(sz for yr, sz in year_sizes.items()
                            if yr.isdigit() and int(yr) < 2025)
            old_ratio = total_old / sz if sz > 0 else 0

            note_parts = ["npm 包缓存（内容寻址）"]
            for yr, ysz in sorted(year_sizes.items()):
                note_parts.append(f"{yr}: {format_size(ysz)}")
            if old_ratio > 0.5:
                note_parts.append(f"~{int(old_ratio*100)}% 为旧版本包")

            results.append(CacheItem(
                path=cacache_dir,
                size=sz,
                provider="npm_deep",
                label="npm 包缓存（按版本）",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "cacache",
                    "year_breakdown": year_sizes,
                    "old_version_ratio": round(old_ratio, 2),
                    "note": " ".join(note_parts),
                    "rebuild_cost": "high" if old_ratio < 0.3 else (
                        "medium" if old_ratio < 0.7 else "low"
                    ),
                },
            ))

    # ── 3. npm global node_modules ──
    npm_global = os.path.join(appdata, "npm", "node_modules")
    if os.path.isdir(npm_global):
        sz = dir_total(npm_global)
        if sz > 0:
            # 列出全局包名
            try:
                pkg_names = [d for d in os.listdir(npm_global)
                             if os.path.isdir(os.path.join(npm_global, d))
                             and not d.startswith(".")]
            except Exception:
                pkg_names = []

            # 尝试检测哪些是"项目内嵌"（大概率无用）
            # npm global 下 node_modules 结构: pkg -> (node_modules -> deps, 没有 parent)
            results.append(CacheItem(
                path=npm_global,
                size=sz,
                provider="npm_deep",
                label="npm 全局 node_modules" + (f" ({len(pkg_names)} packages)" if pkg_names else ""),
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "npm_global",
                    "package_count": len(pkg_names),
                    "packages": pkg_names[:20] if pkg_names else [],
                    "note": "全局安装的 npm 包，可用 npm ls -g --depth=0 查看在用列表。已卸载的包可删",
                    "rebuild_cost": "high",
                },
            ))

    return results


register("npm_deep", _scan_npm_deep)
