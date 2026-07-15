"""pip 缓存深度扫描 — 按文件年龄分组，区分新旧 wheel。

pip 缓存集中在 %LOCALAPPDATA%/pip/cache/ 下，
按 wheel 文件构建时间分组。90% 以上的缓存通常来自旧版本 wheel，
可以被安全裁剪（只保留最近几个月的）。
"""

import os
import time
import math
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size


def _scan_pip_deep(root: str) -> list[CacheItem]:
    results = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")

    pip_cache_dir = os.path.join(local_appdata, "pip", "cache")
    if not os.path.isdir(pip_cache_dir):
        return results

    # 遍历 pip cache 下的所有 .whl 文件，按月份聚合
    month_sizes = {}
    total_files = 0
    total_bytes = 0

    try:
        for dp, dn, fn in os.walk(pip_cache_dir):
            for f in fn:
                if f.endswith(".whl"):
                    fpath = os.path.join(dp, f)
                    try:
                        mtime = os.path.getmtime(fpath)
                        month_key = time.strftime("%Y-%m", time.localtime(mtime))
                        fsz = os.path.getsize(fpath)
                        month_sizes[month_key] = month_sizes.get(month_key, 0) + fsz
                        total_files += 1
                        total_bytes += fsz
                    except Exception:
                        pass
    except Exception:
        pass

    if total_bytes == 0:
        # 可能没有 .whl 文件 -> 当成整体
        return results

    now = time.time()
    # 按年龄分组
    age_groups = {"< 7 days": 0, "7-30 days": 0, "1-3 months": 0,
                  "3-6 months": 0, "6-12 months": 0, "> 12 months": 0}

    for dp, dn, fn in os.walk(pip_cache_dir):
        for f in fn:
            if f.endswith(".whl"):
                try:
                    mtime = os.path.getmtime(os.path.join(dp, f))
                    age = (now - mtime) / 86400
                    if age < 7:
                        age_groups["< 7 days"] += 1
                    elif age < 30:
                        age_groups["7-30 days"] += 1
                    elif age < 90:
                        age_groups["1-3 months"] += 1
                    elif age < 180:
                        age_groups["3-6 months"] += 1
                    elif age < 365:
                        age_groups["6-12 months"] += 1
                    else:
                        age_groups["> 12 months"] += 1
                except Exception:
                    pass

    total_cached = dir_total_approx(pip_cache_dir)
    if total_cached <= 0:
        total_cached = total_bytes

    note = f"pip 缓存文件: {total_files} wheels, {format_size(total_cached)}"
    for grp, cnt in sorted(age_groups.items(), key=lambda x: (
        {"< 7 days": 0, "7-30 days": 1, "1-3 months": 2,
         "3-6 months": 3, "6-12 months": 4, "> 12 months": 5}[x[0]])):
        if cnt > 0:
            note += f"，{grp}({cnt} files)"

    # 估算可安全删除的部分 (> 6 months)
    old_ratio = 0
    if total_files > 0:
        old_count = age_groups.get("6-12 months", 0) + age_groups.get("> 12 months", 0)
        old_ratio = old_count / total_files

    results.append(CacheItem(
        path=pip_cache_dir,
        size=total_cached,
        provider="pip_deep",
        label="pip cache (按文件年龄)",
        safety=SafetyLevel.SAFE,
        extra={
            "type": "pip_cache",
            "total_wheels": total_files,
            "age_breakdown": age_groups,
            "old_ratio": round(old_ratio, 2),
            "note": note,
            "rebuild_cost": "low" if old_ratio > 0.5 else "high",
            "advice": f"~{int(old_ratio*100)}% 的 wheel 文件已超过 6 个月" if old_ratio > 0.3 else "大部分 wheel 是近期缓存的，建议保留",
        },
    ))

    return results


def dir_total_approx(path: str) -> int:
    """快速近似目录大小（仅统计文件，不递归所有子目录）"""
    total = 0
    count = 0
    try:
        for dp, dn, fn in os.walk(path):
            for f in fn:
                count += 1
                if count > 50000:  # 抽样
                    break
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except Exception:
                    pass
            if count > 50000:
                # 采样估计
                est = total / 50000 * count
                return int(est)
    except Exception:
        pass
    return total


register("pip_deep", _scan_pip_deep)
