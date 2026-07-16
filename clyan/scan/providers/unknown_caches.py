"""未知目录深度分析 — 通过文件内容采样判断安全等级。

不再"看目录名猜"，而是:
  1. 列出 userprofile / LocalAppData / AppData 下未被覆盖的目录
  2. 对每个目录 >10MB 的，采样内部文件类型分布
  3. 根据文件类型推断用途: 缓存 / 配置 / 数据库 / 模型 / 混合
  4. 接入现有安全体系 (is_protected / CacheItem / SafetyLevel)
"""

import os
import time
from collections import Counter
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size
from ...utils.dirtree import dir_total
from ...utils.scanner_base import safe_walk
from ...core.config import is_protected


# 文件类型 -> 用途推断
_CACHE_EXTS = {".whl", ".tgz", ".gz", ".zip", ".tar", ".rar", ".7z",
               ".cache", ".tmp", ".temp", ".part", ".download"}
_CONFIG_EXTS = {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg",
                ".conf", ".config", ".env", ".properties"}
_DB_EXTS = {".db", ".sqlite", ".sqlite3", ".db3", ".ldb", ".logdb"}
_MODEL_EXTS = {".bin", ".pt", ".pth", ".gguf", ".ggml", ".safetensors",
               ".onnx", ".pb", ".h5", ".keras", ".pickle", ".pkl"}
_CACHE_DIR_NAMES = {"cache", "caches", "temp", "tmp", "packages",
                    "downloads", "archives", "blob_storage"}
_DATA_DIR_NAMES = {"data", "databases", "db", "config", "settings",
                   "store", "state", "backup", "archive", "sync",
                   "sessions"}


def _sample_directory(dirpath, max_files=30):
    ext_counter = Counter()
    dir_names = set()
    file_count = 0
    try:
        for dp, dn, fn in safe_walk(dirpath, max_depth=2):
            dir_names.update(dn)
            for f in fn:
                file_count += 1
                if file_count > max_files:
                    break
                _, ext = os.path.splitext(f)
                if ext:
                    ext_counter[ext.lower()] += 1
            if file_count > max_files:
                break
    except Exception:
        pass
    has_cache_name = any(
        any(cn in dn.lower() for cn in _CACHE_DIR_NAMES)
        for dn in dir_names
    )
    has_data_name = any(
        any(dn.lower().startswith(cn) or dn.lower() == cn for cn in _DATA_DIR_NAMES)
        for dn in dir_names
    )
    return {
        "file_count": file_count,
        "ext_dist": ext_counter,
        "has_cache_name": has_cache_name,
        "has_data_name": has_data_name,
    }


def _classify(sample, size, age_days):
    """Return (safety, type_str, note_str, cost_str)."""
    ext = sample["ext_dist"]
    total = max(sum(ext.values()), 1)
    has_cache = sample["has_cache_name"]
    has_data = sample["has_data_name"]
    fc = sample["file_count"]

    if fc == 0:
        return SafetyLevel.SAFE, "empty_dir", "空目录，安全可删", "none"

    cache_r = sum(ext.get(e, 0) for e in _CACHE_EXTS) / total
    config_r = sum(ext.get(e, 0) for e in _CONFIG_EXTS) / total
    db_r = sum(ext.get(e, 0) for e in _DB_EXTS) / total
    model_r = sum(ext.get(e, 0) for e in _MODEL_EXTS) / total

    top5 = [f"{e}({c})" for e, c in ext.most_common(5)]

    if cache_r > 0.5:
        return SafetyLevel.SAFE, "package_cache", \
               f"包缓存 ({fc} 文件)", "high"
    if model_r > 0.3 or (size > 500_000_000 and model_r > 0.1):
        return SafetyLevel.CAUTION, "model_cache", \
               f"ML 模型 ({fc} 文件)", "high"
    if db_r > 0.3:
        sl = SafetyLevel.UNSAFE if has_data else SafetyLevel.CAUTION
        return sl, "database", f"数据库 ({fc} 文件)", "high"
    if config_r > 0.5:
        return SafetyLevel.UNSAFE, "config", f"配置文件 ({fc} 文件)", "high"
    if has_data:
        return SafetyLevel.CAUTION, "app_data", \
               "含 data/store 子目录", "medium"
    if has_cache:
        return SafetyLevel.SAFE, "app_cache", \
               "含 cache 子目录", "low"
    if age_days > 180 and total < 10:
        return SafetyLevel.SAFE, "old_data", \
               f">180天未改 ({fc} 文件)", "low"

    top_exts = ", ".join(top5[:4]) if top5 else "(无文件)"
    return SafetyLevel.CAUTION, "mixed", \
           f"{fc} 文件 [{top_exts}]", "unknown"


def _scan_unknown_caches(root):
    """Scan directories no existing provider covers."""
    results = []
    up = os.environ.get("USERPROFILE", "")
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    now = time.time()

    candidates = []

    # ~/.xxx 目录
    if up and os.path.isdir(up):
        try:
            for e in os.listdir(up):
                if e.startswith("."):
                    ep = os.path.join(up, e)
                    if os.path.isdir(ep):
                        candidates.append((ep, "~"))
        except Exception:
            pass

    # LocalAppData 下
    if local and os.path.isdir(local):
        try:
            for e in os.listdir(local):
                ep = os.path.join(local, e)
                if os.path.isdir(ep) and not e.startswith("."):
                    candidates.append((ep, "LocalAppData"))
        except Exception:
            pass

    # AppData 下
    if roaming and os.path.isdir(roaming):
        try:
            for e in os.listdir(roaming):
                ep = os.path.join(roaming, e)
                if os.path.isdir(ep) and not e.startswith("."):
                    candidates.append((ep, "AppData"))
        except Exception:
            pass

    budget_end = time.time() + 5
    for dpath, src in candidates:
        try:
            sz = dir_total(dpath)
        except Exception:
            sz = 0
        if time.time() > budget_end:
            break
        if sz < 10_000_000:
            continue

        if is_protected(dpath):
            continue

        name = os.path.basename(dpath)
        try:
            age = (now - os.path.getmtime(dpath)) / 86400
        except Exception:
            age = -1

        sample = _sample_directory(dpath)
        safety, dtype, note, cost = _classify(sample, sz, age)

        item = CacheItem(
            path=dpath, size=sz,
            provider="unknown_caches",
            label=f"未知: {name} ({src}, {format_size(sz)})",
            safety=safety,
            extra={
                "type": dtype,
                "source": src, "dir_name": name,
                "age_days": int(age) if age >= 0 else -1,
                "file_count": sample["file_count"],
                "has_cache_subdir": sample["has_cache_name"],
                "has_data_subdir": sample["has_data_name"],
                "rebuild_cost": cost, "note": note,
            },
        )
        results.append(item)

    return results


register("unknown_caches", _scan_unknown_caches)
