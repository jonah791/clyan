"""Clyan Reflex — 无意识磁盘反射弧。

这不是"工具"，这是 disk reflex（磁盘的膝跳反射）。
AI 不需要"思考清理"这件事——当磁盘将满时，reflex 自动处理。

三个反射级别（从轻到重）:
  Level 1 (tick):   statvfs 快速健康检查 —— 不扫描，不 IO，<1ms
  Level 2 (twitch): 安全清理 —— 只删 cost=none 项，AI 无感
  Level 3 (spasm):  紧急清理 —— AI 被告知，但不需要做决定
"""

import os
import json
import time
from typing import Optional
from .utils.size import format_size
from .core.history import get_disk_trend
from .scan.dev_garbage import DevGarbageScanner
from .clean.execute import delete_items
from .utils.dirtree import dir_total


# ── Pulse state cache ─────────────────────────────────────
# Updated after every scan. read by check_disk_pulse.
# This is what makes the reflex INSTANT (no scan needed).

_CACHE_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "clyan", "disk_pulse.json",
)


def _get_disk_free(path: str = "C:\\") -> tuple[int, int, int]:
    """Get (total, free, used) bytes for a drive path."""
    try:
        import ctypes
        free_bytes = ctypes.c_ulonglong(0)
        total_bytes = ctypes.c_ulonglong(0)
        total_free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            path, ctypes.byref(free_bytes),
            ctypes.byref(total_bytes), ctypes.byref(total_free_bytes),
        )
        return (total_bytes.value, free_bytes.value, total_bytes.value - free_bytes.value)
    except Exception:
        s = os.statvfs(path)
        free = s.f_frsize * s.f_bavail
        total = s.f_frsize * s.f_blocks
        return (total, free, total - free)


def _read_pulse_cache() -> dict:
    """Read cached pulse state. Returns empty dict if missing/stale (>1h)."""
    try:
        if os.path.isfile(_CACHE_PATH):
            data = json.loads(open(_CACHE_PATH, encoding="utf-8").read())
            cache_age = time.time() - data.get("cached_at", 0)
            if cache_age < 3600:  # 1h TTL
                return data
    except Exception:
        pass
    return {}


def _write_pulse_cache(data: dict) -> None:
    """Write pulse state cache."""
    try:
        data["cached_at"] = time.time()
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        open(_CACHE_PATH, "w", encoding="utf-8").write(json.dumps(data, indent=1))
    except Exception:
        pass


def _update_pulse_after_scan(path: str, scan_result: dict) -> None:
    """Call after any scan to update the pulse cache."""
    try:
        total, free, used = _get_disk_free(path)
        cache = {
            "path": path,
            "total_gb": round(total / 1e9, 1),
            "free_gb": round(free / 1e9, 1),
            "free_pct": round(free / total * 100, 1) if total else 0,
            "used_gb": round(used / 1e9, 1),
        }

        # Calculate safe reclaimable (cost=none items)
        safe_reclaimable = 0
        cost_none_reclaimable = 0
        for item in scan_result.get("items", []):
            if item.get("recovery_cost") == "none" or item.get("extra", {}).get("recovery_cost") == "none":
                cost_none_reclaimable += item.get("size", 0)
                safe_reclaimable += item.get("size", 0)
            elif item.get("safety") == "safe":
                safe_reclaimable += item.get("size", 0)

        cache["safe_reclaimable_gb"] = round(safe_reclaimable / 1e9, 1)
        cache["cost_none_reclaimable_gb"] = round(cost_none_reclaimable / 1e9, 1)

        # Trend from history
        try:
            trend = get_disk_trend(path, limit=14)
            if len(trend) >= 2:
                first = trend[0]
                last = trend[-1]
                days = max((last["timestamp"] - first["timestamp"]) / 86400, 1)
                growth = (first["free_size"] - last["free_size"]) / days
                cache["growth_rate_gb_per_week"] = round(growth * 7 / 1e9, 2)
                if growth > 0:
                    cache["days_until_critical"] = int(last["free_size"] / growth)
                else:
                    cache["days_until_critical"] = -1
        except Exception:
            pass

        _write_pulse_cache(cache)
    except Exception:
        pass


# ── Reflex Level 1: Tick ──────────────────────────────────

def check_pulse(path: str = "C:\\") -> dict:
    """Instant health check. No scan — uses cached state + statvfs.

    Returns:
      status: 'healthy' | 'warning' | 'critical'
      free_gb, free_pct, safe_reclaimable_gb, days_until_critical
    """
    total, free, used = _get_disk_free(path)
    free_gb = round(free / 1e9, 1)
    free_pct = round(free / total * 100, 1) if total else 0

    cache = _read_pulse_cache()

    # Determine status
    if free_pct < 5 or free_gb < 5:
        status = "critical"
    elif free_pct < 15 or free_gb < 20:
        status = "warning"
    else:
        status = "healthy"

    result = {
        "status": status,
        "path": path,
        "total_gb": round(total / 1e9, 1),
        "free_gb": free_gb,
        "free_pct": free_pct,
        "used_gb": round(used / 1e9, 1),
        "safe_reclaimable_gb": cache.get("cost_none_reclaimable_gb", 0),
        "days_until_critical": cache.get("days_until_critical", -1),
    }

    # If no cached data, do a lightweight best-effort estimate
    if result["safe_reclaimable_gb"] == 0 and (status == "warning" or status == "critical"):
        result["note"] = "Run a scan first for reclaimable space estimates (scan_quick)"

    return result


# ── Reflex Level 2: Twitch ────────────────────────────────

def auto_clear_safe(path: str = "C:\\", target_gb: float = 0) -> dict:
    """Auto-clear all cost=none items. AI doesn't need to think.

    Only deletes items with recovery_cost='none' — these are guaranteed
    safe (Temp, npx binaries, thumbnail cache, WER reports, etc.).
    Uses recycle bin by default.

    Args:
      path: root path to scan
      target_gb: if > 0, stop after reclaiming this much
    """
    start = time.time()

    # 1. Scan
    scanner = DevGarbageScanner(root=path)
    scan_result = scanner.scan().to_dict()
    items = scan_result.get("items", [])

    # 2. Filter cost=none
    safe_items = []
    for item in items:
        cost = item.get("recovery_cost") or item.get("extra", {}).get("recovery_cost", "unknown")
        if cost == "none":
            safe_items.append(item)

    if not safe_items:
        return {
            "reclaimed_gb": 0,
            "reclaimed_human": "0 B",
            "items_cleared": 0,
            "message": "No cost=none items found to auto-clear.",
            "ellapsed_ms": (time.time() - start) * 1000,
        }

    # 3. Sort by size descending (maximize gain per item)
    safe_items.sort(key=lambda i: -i.get("size", 0))

    # 4. Apply target_gb limit
    selected = safe_items
    if target_gb > 0:
        target_bytes = int(target_gb * 1e9)
        accumulated = 0
        selected = []
        for item in safe_items:
            if accumulated >= target_bytes:
                break
            selected.append(item)
            accumulated += item.get("size", 0)

    # 5. Execute (use trash by default for safety)
    result = delete_items(selected, use_trash=True, fast=False)

    # 6. Update pulse cache
    _update_pulse_after_scan(path, {"items": selected})

    return {
        "reclaimed_gb": round(result.get("total_freed", 0) / 1e9, 2),
        "reclaimed_human": result.get("total_freed_human", "0 B"),
        "items_cleared": result.get("success_count", 0),
        "items_failed": result.get("fail_count", 0),
        "actual_freed_human": result.get("actual_freed_human", "0 B"),
        "protected_paths_skipped": len(result.get("protected_skipped", []) or []),
        "target_gb": target_gb if target_gb > 0 else None,
        "ellapsed_ms": (time.time() - start) * 1000,
        "message": f"Auto-cleared {result.get('success_count', 0)} items, freed {result.get('total_freed_human', '0 B')}.",
    }
