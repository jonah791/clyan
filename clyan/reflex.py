"""Clyan Reflex — 无意识磁盘反射弧。

这不是"工具"，这是 disk reflex（磁盘的膝跳反射）。
AI 不需要"思考清理"这件事——当磁盘将满时，reflex 自动处理。

三个反射级别:
  Level 1 (tick):   statvfs 健康检查 —— <1ms，缓存预热后零 IO
  Level 2 (twitch): 安全清理 —— 只删 cost=none 项，AI 无感
  Level 3 (spasm):  紧急清理 —— AI 被告知，但不需要做决定
"""

import os
import json
import time
from .utils.size import format_size
from .core.history import get_disk_trend
from .clean.execute import delete_items
from .utils.dirtree import dir_total


# ── Pulse state cache ─────────────────────────────────────
_CACHE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    "clyan",
)
_CACHE_PATH = os.path.join(_CACHE_DIR, "disk_pulse.json")


def _get_disk_free(path: str = "C:\\") -> tuple[int, int, int]:
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


def _read_pulse_cache(max_age: int = 3600) -> dict:
    try:
        if os.path.isfile(_CACHE_PATH):
            data = json.loads(open(_CACHE_PATH, encoding="utf-8").read())
            if time.time() - data.get("cached_at", 0) < max_age:
                return data
    except Exception:
        pass
    return {}


def _write_pulse_cache(data: dict) -> None:
    try:
        data["cached_at"] = time.time()
        os.makedirs(_CACHE_DIR, exist_ok=True)
        open(_CACHE_PATH, "w", encoding="utf-8").write(json.dumps(data, indent=1))
    except Exception:
        pass


def _refresh_pulse_cache(path: str, scan_result: dict) -> None:
    """Update pulse cache from scan results."""
    try:
        total, free, used = _get_disk_free(path)
        cache = {
            "path": path,
            "total_gb": round(total / 1e9, 1),
            "free_gb": round(free / 1e9, 1),
            "free_pct": round(free / total * 100, 1) if total else 0,
            "used_gb": round(used / 1e9, 1),
        }
        safe_reclaimable = 0
        cost_none_reclaimable = 0
        for item in scan_result.get("items", []):
            cost = item.get("recovery_cost") or item.get("extra", {}).get("recovery_cost", "")
            if cost == "none":
                cost_none_reclaimable += item.get("size", 0)
                safe_reclaimable += item.get("size", 0)
            elif item.get("safety") == "safe":
                safe_reclaimable += item.get("size", 0)
        cache["safe_reclaimable_gb"] = round(safe_reclaimable / 1e9, 1)
        cache["cost_none_reclaimable_gb"] = round(cost_none_reclaimable / 1e9, 1)

        # Trend
        try:
            trend = get_disk_trend(path, limit=14)
            if len(trend) >= 2:
                first = trend[0]; last = trend[-1]
                days = max((last["timestamp"] - first["timestamp"]) / 86400, 1)
                growth = (first["free_size"] - last["free_size"]) / days
                cache["growth_rate_gb_per_week"] = round(growth * 7 / 1e9, 2)
                cache["days_until_critical"] = int(last["free_size"] / growth) if growth > 0 else -1
        except Exception:
            pass
        _write_pulse_cache(cache)
    except Exception:
        pass


def _lightweight_estimate(path: str) -> dict:
    """Quick estimate of safe-reclaimable space by checking known cache dirs.
    Takes <100ms — no full scan, just checks a handful of well-known dirs.
    Used to warm the pulse cache when no scan has been run yet.
    """
    reclaimable = 0
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    up = os.environ.get("USERPROFILE", "")
    windir = os.environ.get("WINDIR", "C:\\Windows")

    # Only check directories that are guaranteed cost=none
    quick_checks = {
        "npx": os.path.join(local_appdata, "npm-cache", "_npx"),
        "thumbnail": os.path.join(local_appdata, "Microsoft", "Windows", "Explorer"),
        "wer": os.path.join(local_appdata, "Microsoft", "Windows", "WER"),
        "recent": os.path.join(appdata, "Microsoft", "Windows", "Recent"),
        "prefetch": os.path.join(windir, "Prefetch"),
    }
    for name, p in quick_checks.items():
        if p and os.path.isdir(p):
            try:
                reclaimable += dir_total(p)
            except Exception:
                pass

    return {
        "status": "unknown",
        "safe_reclaimable_gb": round(reclaimable / 1e9, 1),
        "cost_none_reclaimable_gb": round(reclaimable / 1e9, 1),
    }


# ── Reflex Level 1: Tick ──────────────────────────────────

def check_pulse(path: str = "C:\\") -> dict:
    """Instant health check. Uses cached state + statvfs.

    Auto-warms: if cache is missing, does a <100ms lightweight
    estimate so you never see 0 reclaimable on first call.
    """
    t0 = time.time()
    total, free, used = _get_disk_free(path)
    free_gb = round(free / 1e9, 1)
    free_pct = round(free / total * 100, 1) if total else 0

    cache = _read_pulse_cache()
    is_cached = bool(cache)

    if free_pct < 5 or free_gb < 5:
        status = "critical"
    elif free_pct < 15 or free_gb < 20:
        status = "warning"
    else:
        status = "healthy"

    # Use cached reclaimable data, or warm if missing
    if is_cached:
        safe_reclaimable_gb = cache.get("cost_none_reclaimable_gb", 0)
        days_critical = cache.get("days_until_critical", -1)
        growth = cache.get("growth_rate_gb_per_week")
    else:
        # Auto-warm: lightweight estimate (<100ms)
        est = _lightweight_estimate(path)
        safe_reclaimable_gb = est["safe_reclaimable_gb"]
        growth = None
        days_critical = -1
        # Store the warm estimate so next pulse doesn't re-calc
        warm_cache = {
            "path": path, "total_gb": round(total / 1e9, 1),
            "free_gb": free_gb, "free_pct": free_pct,
            "used_gb": round(used / 1e9, 1),
            "safe_reclaimable_gb": safe_reclaimable_gb,
            "cost_none_reclaimable_gb": safe_reclaimable_gb,
        }
        _write_pulse_cache(warm_cache)

    return {
        "status": status,
        "path": path,
        "total_gb": round(total / 1e9, 1),
        "free_gb": free_gb,
        "free_pct": free_pct,
        "used_gb": round(used / 1e9, 1),
        "safe_reclaimable_gb": safe_reclaimable_gb,
        "days_until_critical": days_critical,
        "growth_rate_gb_per_week": growth,
        "cached": is_cached,
        "ellapsed_ms": round((time.time() - t0) * 1000, 1),
    }


# ── Reflex Level 2: Twitch ────────────────────────────────

def auto_clear_safe(path: str = "C:\\", target_gb: float = 0,
                    use_cached: bool = True) -> dict:
    """Auto-clear cost=none items. AI doesn't need to think.

    Uses cached scan results if available (instant execution).
    Only falls back to full scan when cache is stale.

    Args:
      path: root path to scan
      target_gb: stop after reclaiming this much (0 = all)
      use_cached: if True, reuse cached data instead of re-scanning
    """
    start = time.time()
    total, free, _ = _get_disk_free(path)
    before_free = free

    # Try cached data first
    items = []
    if use_cached:
        cache = _read_pulse_cache(max_age=7200)  # 2h TTL for auto-clear
        if cache and cache.get("scan_items"):
            for item_data in cache["scan_items"]:
                cost = item_data.get("recovery_cost") or \
                       item_data.get("extra", {}).get("recovery_cost", "")
                if cost == "none":
                    items.append(item_data)

    # Fall back to full scan if no cached data
    if not items:
        from .scan.dev_garbage import DevGarbageScanner
        scanner = DevGarbageScanner(root=path)
        scan_result = scanner.scan().to_dict()
        all_items = scan_result.get("items", [])
        for item in all_items:
            cost = item.get("recovery_cost") or item.get("extra", {}).get("recovery_cost", "unknown")
            if cost == "none":
                items.append(item)
        # Cache the scan items for next time
        try:
            c = _read_pulse_cache(max_age=999999)
            c["scan_items"] = all_items
            _write_pulse_cache(c)
        except Exception:
            pass

    if not items:
        return {
            "reclaimed_gb": 0, "reclaimed_human": "0 B",
            "items_cleared": 0, "items_failed": 0,
            "message": "No cost=none items found.",
            "ellapsed_ms": (time.time() - start) * 1000,
        }

    items.sort(key=lambda i: -i.get("size", 0))
    if target_gb > 0:
        target_bytes = int(target_gb * 1e9)
        acc = 0
        selected = []
        for item in items:
            if acc >= target_bytes:
                break
            selected.append(item)
            acc += item.get("size", 0)
        items = selected

    result = delete_items(items, use_trash=True, fast=False)
    _refresh_pulse_cache(path, {"items": items})

    # Measure actual freed space
    _, after_free, _ = _get_disk_free(path)
    actual_freed = max(after_free - before_free, 0)

    return {
        "reclaimed_gb": round(result.get("total_freed", 0) / 1e9, 2),
        "reclaimed_human": result.get("total_freed_human", "0 B"),
        "actual_freed_human": format_size(actual_freed),
        "items_cleared": result.get("success_count", 0),
        "items_failed": result.get("fail_count", 0),
        "protected_paths_skipped": len(result.get("protected_skipped", []) or []),
        "target_gb": target_gb if target_gb > 0 else None,
        "ellapsed_ms": (time.time() - start) * 1000,
        "message": f"Auto-cleared {result.get('success_count', 0)} items, "
                   f"freed {result.get('total_freed_human', '0 B')} "
                   f"(actual: {format_size(actual_freed)}).",
    }
