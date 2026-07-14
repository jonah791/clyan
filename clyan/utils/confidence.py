"""Confidence scoring engine for cache cleanup items.

Combines multiple signals into a 0.0–1.0 score and a human-readable reason.
"""

from __future__ import annotations

from ..core.config import DangerLevel


# ── Known-safe directory names (boost confidence) ──
_KNOWN_SAFE = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".cache", ".parcel-cache", "coverage", "npm_cache", "pip_cache",
    "bun_cache", "go_cache", "pub_cache", "thumbnail_cache",
    "system_temp", "recycle_bin", ".gradle", "npm-cache",
    "Temp", "tmp", "Code Cache", "GPUCache", "CachedData",
    "CachedExtensionVSIXs", "ComponentModelCache", "blob_storage",
    "cache2", "delivery_opt", "font_cache", "prefetch",
    "NativeImages_v4", "NativeImages_v2",
}


def compute(item: dict) -> tuple[float, list[str]]:
    """Score an item dict (from CacheItem.to_dict() or ScanResult.items).

    Returns (score 0.0–1.0, list of reason fragments).
    """
    reasons: list[str] = []
    score = 0.0

    # 1. Safety level (weight 40%)
    safety = item.get("safety", "unsafe")
    if safety == "safe":
        score += 40.0
        reasons.append("安全级别 SAFE")
    elif safety == "caution":
        score += 20.0
        reasons.append("安全级别 CAUTION")
    else:
        reasons.append("安全级别 UNSAFE")

    # 2. Staleness (weight 30%)
    age = item.get("age_days", -1)
    if age >= 90:
        score += 30.0
        reasons.append(f">90天未修改")
    elif age >= 30:
        score += 20.0
        reasons.append(f"{age}天未修改")
    elif age >= 7:
        score += 10.0
        reasons.append(f"{age}天未修改")
    elif age >= 0:
        reasons.append(f"近期使用（{age}天前）")
    else:
        reasons.append("年龄未知")

    # 3. Tool installed (weight 20%) — orphans get a big boost
    tool_ok = item.get("tool_installed", True)
    if tool_ok is False:
        score += 20.0
        reasons.append("对应工具已卸载")
    else:
        reasons.append("工具仍在系统中")

    # 4. Known-safe directory name (weight 10%)
    path = item.get("path", "")
    path_lower = path.lower().replace("\\", "/")
    parts = path_lower.split("/")
    is_known = any(p in _KNOWN_SAFE for p in parts)
    if is_known:
        score += 10.0
        reasons.append("已知安全缓存目录名")
    else:
        reasons.append("非常见缓存目录")

    return round(min(score / 100.0, 1.0), 2), reasons


def compute_and_attach(item: dict) -> None:
    """Compute confidence + reason for *item* and store in-place."""
    score, reasons = compute(item)
    item["confidence"] = score
    item["reason"] = "；".join(reasons)
