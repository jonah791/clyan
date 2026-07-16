"""Clyan Reclaim — 统一回收计划。

不是扫描，不是清理。是"扫描 → 去重 → 排序 → 分阶段 → 执行"的完整流水线。

AI 或用户跑一次 reclaim，拿到一个按风险分阶段的执行计划。
然后说"执行 phase 1"——就这么简单。
"""

import os
import time
from typing import Any
from .utils.size import format_size
from .clean.execute import delete_items
from .reflex import _refresh_pulse_cache
from .report import build_report, _enrich_items


def reclaim(path: str = "C:\\") -> dict:
    """Full reclaim scan on one or all drives.
    
    Args:
      path: single path like "C:\\" or "all" to scan all available drives
    """
    if path.lower() == "all":
        # Scan all available drives
        drives = []
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            dp = f"{letter}:\\"
            if os.path.isdir(dp):
                drives.append(dp)
        if not drives:
            return {"error": "No additional drives found", "path": "all", "phases": []}
        
        combined = {"path": "all", "total_size": 0, "total_items": 0,
                     "phases": [], "recommendation": "", "scan_times_ms": {}}
        for drive in drives:
            try:
                plan = _reclaim_single(drive)
                for phase in plan.get("phases", []):
                    # Merge phases across drives
                    for cp in combined["phases"]:
                        if cp["cost"] == phase["cost"]:
                            cp["item_count"] += phase["item_count"]
                            cp["total_size"] += phase["total_size"]
                            # Don't merge items (too large)
                            break
                    else:
                        combined["phases"].append(phase)
                combined["total_size"] += plan["total_size"]
                combined["total_items"] += plan["total_items"]
                combined["scan_times_ms"][drive] = plan.get("scan_times_ms", {})
            except Exception as e:
                combined["scan_times_ms"][drive] = str(e)
        
        combined["total_size_human"] = format_size(combined["total_size"])
        combined["recommendation"] = _make_recommendation(combined["phases"], combined["total_size"])
        return combined
    
    return _reclaim_single(path)


def _reclaim_single(path: str) -> dict:
    """Full reclaim scan: all scanners → aggregate → dedupe → phase plan.

    Returns a dict with:
      - phases: list of {cost, count, size, size_human, items}
      - total_size, total_items
      - recommendation: str
      - scan details
    """
    start = time.time()

    # 1. Run all scanners in parallel
    all_items: list[dict] = []
    scan_times = {}

    from .scan.dev_garbage import DevGarbageScanner
    from .scan.system import SystemScanner
    from .scan.browser_cache import BrowserCacheScanner

    scanners = {
        "dev_garbage": lambda: DevGarbageScanner(root=path),
        "system": SystemScanner,
        "browsers": BrowserCacheScanner,
    }

    for name, factory in scanners.items():
        t0 = time.time()
        try:
            s = factory()
            data = s.scan().to_dict()
            items = data.get("items", [])
            for item in items:
                item.setdefault("_scanner", name)
            all_items.extend(items)
            scan_times[name] = round((time.time() - t0) * 1000)
        except Exception as e:
            scan_times[name] = str(e)

    # 2. Deduplicate by path (keep first occurrence)
    seen = set()
    deduped = []
    for item in all_items:
        p = item.get("path", "")
        if p and p not in seen:
            seen.add(p)
            deduped.append(item)
        elif not p:
            deduped.append(item)

    # 3-6. Use report layer: enrich + sort + phase + recommendation
    report = build_report(deduped, path)
    phases = report["phases"]
    total_size = report["total_size"]
    total_items = report["total_items"]
    recommendation = report["recommendation"]

    # 7. Update pulse cache
    _refresh_pulse_cache(path, {"items": deduped})

    return {
        "path": path,
        "total_size": total_size,
        "total_size_human": format_size(total_size),
        "total_items": total_items,
        "phases": phases,
        "recommendation": recommendation,
        "scan_times_ms": scan_times,
        "ellapsed_ms": (time.time() - start) * 1000,
        "items": deduped[:50],
    }





def execute_phase(plan: dict, phase_cost: str, use_trash: bool = True,
                  fast: bool = False) -> dict:
    """Execute a single phase from a reclaim plan."""
    for phase in plan.get("phases", []):
        if phase["cost"] == phase_cost:
            items = phase.get("items", [])
            if not items:
                return {"error": f"No items in phase '{phase_cost}'"}
            result = delete_items(items, use_trash=use_trash, fast=fast)
            result["phase"] = phase_cost
            result["total_in_phase"] = len(items)
            result["phase_size_human"] = phase.get("total_size_human", "0 B")
            return result
    return {"error": f"Phase '{phase_cost}' not found in plan"}
