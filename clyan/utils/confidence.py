"""Confidence scoring engine for cache cleanup items.

Combines multiple signals into a 0.0–1.0 score and a human-readable reason.
"""
from __future__ import annotations
import os

from ..core.config import DangerLevel

# ── Rebuild cost levels ──────────────────────────────────────────────
# Set on item["rebuild_cost"] by providers or inferred by _enrich.
REBUILD_NONE = "none"   # Auto-regenerated, no network (Temp, WER, browser cache)
REBUILD_LOW = "low"     # Local rebuild, fast (< 1 min)
REBUILD_HIGH = "high"   # Network download required (pip, npm, cargo, etc.)


def infer_rebuild_cost(provider: str, path: str) -> str:
    """Infer rebuild cost from provider name or path heuristics."""
    p = (provider or "").lower()

    _HIGH_PROVIDERS = {
        "npm_cache", "pip_cache", "cargo_registry", "nuget_cache",
        "go_cache", "gradle_cache", "docker_images", "maven_cache",
        "bun_cache", "pnpm_cache", "uv_cache",
    }
    _LOW_PROVIDERS = {
        "ide", "vscode_cache", "vscode_extensions", "jetbrains_cache",
        "jetbrains_index", "jetbrains_tmp", "android_studio",
        "build_artifacts", "cmake_build",
    }

    if p in _HIGH_PROVIDERS:
        return REBUILD_HIGH
    if p in _LOW_PROVIDERS:
        return REBUILD_LOW

    # Path heuristics for fast_scan / generic dict items
    if path:
        pl = path.lower().replace("\\", "/")
        if "/node_modules/" in pl or pl.endswith("/node_modules"):
            return REBUILD_HIGH
        if "/.m2/" in pl:
            return REBUILD_HIGH
        if "/build/" in pl or "/target/" in pl or "/_deps/" in pl:
            return REBUILD_LOW
        if "/.next/" in pl or "/.turbo/" in pl or "/__pycache__/" in pl:
            return REBUILD_LOW
        if "/temp/" in pl or "/tmp/" in pl:
            return REBUILD_NONE

    return REBUILD_NONE


# ── Known-safe directory names (boost confidence) ──
# All lowercase for case-insensitive matching against path parts.
_KNOWN_SAFE = {
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".cache", ".parcel-cache", "coverage", "npm_cache", "pip_cache",
    "bun_cache", "go_cache", "pub_cache", "thumbnail_cache",
    "system_temp", "recycle_bin", ".gradle", "npm-cache",
    "temp", "tmp", "code cache", "gpucache", "cacheddata",
    "cachedextensionvsixs", "componentmodelcache", "blob_storage",
    "cache2", "delivery_opt", "font_cache", "prefetch",
    "nativeimages_v4", "nativeimages_v2",
}

# ── Orphan temp dir prefixes ──
_ORPHAN_PREFIXES = ("pip-unpack-", "npm-", "tmp-", "conda-", "msi-", "vs_")


def compute(item: dict) -> tuple[float, list[str]]:
    """Score an item dict — returns (0.0–1.0, list of reason fragments).

    v0.7.0 weights:
      安全级别    30%  — safe=30, caution=15, unsafe=0
      陈旧度     25%  — ≥90d=25, ≥30d=17, ≥7d=8
      工具已卸载  15%  — gone=15
      已知目录名  10%  — known name or orphan prefix
      孤儿标记   10%  — explicit orphan flag
      重建成本   20%  — none=20, low=5, high=-20
      ────────
      Max 110 → ÷100 → cap at 1.0
    """
    reasons: list[str] = []
    score = 0.0

    # 1. Safety (30%)
    safety = item.get("safety", "unsafe")
    if safety == "safe":
        score += 30.0; reasons.append("安全级别 SAFE")
    elif safety == "caution":
        score += 15.0; reasons.append("安全级别 CAUTION")
    else:
        reasons.append("安全级别 UNSAFE")

    # 2. Staleness (25%)
    age = item.get("age_days", -1)
    if age >= 90:
        score += 25.0; reasons.append(f">90天未修改")
    elif age >= 30:
        score += 17.0; reasons.append(f"{age}天未修改")
    elif age >= 7:
        score += 8.0; reasons.append(f"{age}天未修改")
    elif age >= 0:
        reasons.append(f"近期使用（{age}天前）")
    else:
        reasons.append("年龄未知")

    # 3. Tool installed (15%)
    tool_ok = item.get("tool_installed", True)
    if tool_ok is False:
        score += 15.0; reasons.append("对应工具已卸载")
    else:
        reasons.append("工具仍在系统中")

    # 4. Known directory name (10%)
    path = item.get("path", "")
    basename = os.path.basename(path).lower() if path else ""
    pl = path.lower().replace("\\", "/")
    parts = pl.split("/")
    is_known = any(p in _KNOWN_SAFE for p in parts)
    is_orphan_name = any(basename.startswith(p) for p in _ORPHAN_PREFIXES)

    if is_known:
        score += 10.0; reasons.append("已知安全缓存目录名")
    elif is_orphan_name:
        score += 10.0; reasons.append("孤儿临时目录（pip/conda 等残留）")
    else:
        reasons.append("非常见缓存目录")

    # 5. Orphan flag (10%)
    if item.get("orphan"):
        score += 10.0; reasons.append("已标记为孤儿缓存")

    # 6. Rebuild cost (20%)
    rebuild = item.get("rebuild_cost", REBUILD_NONE)
    if rebuild == REBUILD_NONE:
        score += 20.0; reasons.append("重建无成本")
    elif rebuild == REBUILD_LOW:
        score += 5.0; reasons.append("重建成本低（本地重建快）")
    else:
        score -= 20.0; reasons.append("⚠ 重建成本高（需网络下载）")

    return round(min(score / 100.0, 1.0), 2), reasons


def compute_and_attach(item: dict) -> None:
    """Compute confidence + reason for *item* and store in-place."""
    if "rebuild_cost" not in item:
        item["rebuild_cost"] = infer_rebuild_cost(
            item.get("provider", ""), item.get("path", ""),
        )
    score, reasons = compute(item)
    item["confidence"] = score
    item["reason"] = "；".join(reasons)
