import os
import json
import subprocess
import glob
import re
import time as time_module
from pathlib import Path
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total
from ..utils.system_drive import system_root_path as win_path


# Cache the dism /AnalyzeComponentStore result for 6 hours
_WINSXS_CACHE_TTL = 21600  # 6 hours
_WINSXS_CACHE_PATH = Path(
    os.environ.get("LOCALAPPDATA", "")
) / "clyan" / "winsxs_cache.json"


def _load_winsxs_cache() -> dict | None:
    try:
        if _WINSXS_CACHE_PATH.exists():
            data = json.loads(_WINSXS_CACHE_PATH.read_text())
            if time_module.time() - data.get("ts", 0) < _WINSXS_CACHE_TTL:
                return data
    except Exception:
        pass
    return None


def _save_winsxs_cache(store_size: int, reclaimable: int) -> None:
    try:
        _WINSXS_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _WINSXS_CACHE_PATH.write_text(json.dumps({
            "ts": time_module.time(),
            "store_size": store_size,
            "reclaimable": reclaimable,
        }))
    except Exception:
        pass


def _scan_winsxs(root: str) -> list[CacheItem]:
    windir = os.environ.get("WINDIR", win_path("Windows"))
    winsxs = os.path.join(windir, "WinSxS")
    if not os.path.isdir(winsxs):
        return []

    # Check cache first
    cached = _load_winsxs_cache()
    if cached is not None:
        store_size = cached["store_size"]
        reclaimable = cached["reclaimable"]
    else:
        # Run dism to get size + reclaimable (avoids 10s+ dir_total walk of WinSxS)
        store_size = 0
        reclaimable = 0
        try:
            result = subprocess.run(
                ["dism", "/online", "/Cleanup-Image", "/AnalyzeComponentStore", "/english"],
                capture_output=True, text=True, timeout=120
            )
            for line in result.stdout.splitlines():
                lc = line.lower()
                m = re.search(r"([\d.]+)\s*(mb|gb)", lc)
                if not m:
                    continue
                val = float(m.group(1))
                multiplier = 1024**3 if m.group(2) == "gb" else 1024**2
                if "component store" in lc:
                    store_size = int(val * multiplier)
                if "reclaimable" in lc:
                    reclaimable = int(val * multiplier)
        except Exception:
            pass

        # Fallback: walk the tree
        if store_size == 0:
            store_size = dir_total(winsxs)

        _save_winsxs_cache(store_size, reclaimable)

    if store_size > 0:
        label = f"WinSxS (component store, {store_size/(1024**3):.1f} GB"
        if reclaimable:
            label += f", ~{reclaimable/(1024**3):.1f} GB reclaimable"
        label += ")"
        return [CacheItem(
            path=winsxs, size=store_size, provider="win_deep",
            label=label, safety=SafetyLevel.SAFE,
            extra={"type": "winsxs", "reclaimable": reclaimable, "admin_required": True},
        )]
    return []


def _scan_windows_old(root: str) -> list[CacheItem]:
    results = []
    win_old = "C:\\Windows.old"
    if os.path.isdir(win_old):
        sz = dir_total(win_old)
        if sz > 0:
            results.append(CacheItem(
                path=win_old, size=sz, provider="win_deep",
                label="Windows.old (previous installation)",
                safety=SafetyLevel.SAFE,
                extra={"type": "windows_old", "admin_required": True},
            ))
    return results


def _scan_driver_store(root: str) -> list[CacheItem]:
    results = []
    windir = os.environ.get("WINDIR", win_path("Windows"))
    drv = os.path.join(windir, "System32", "DriverStore", "FileRepository")
    if os.path.isdir(drv):
        sz = dir_total(drv)
        if sz > 0:
            results.append(CacheItem(
                path=drv, size=sz, provider="win_deep",
                label="Driver Store (FileRepository)",
                safety=SafetyLevel.SAFE,
                extra={"type": "driver_store", "admin_required": True},
            ))
    return results


def _scan_dotnet_ngen(root: str) -> list[CacheItem]:
    results = []
    windir = os.environ.get("WINDIR", win_path("Windows"))
    for asm_dir in glob.glob(os.path.join(windir, "assembly", "NativeImages_v*")):
        if os.path.isdir(asm_dir):
            sz = dir_total(asm_dir)
            if sz > 0:
                label = os.path.basename(asm_dir)
                results.append(CacheItem(
                    path=asm_dir, size=sz, provider="win_deep",
                    label=f".NET NGEN ({label})",
                    safety=SafetyLevel.SAFE,
                    extra={"type": "dotnet_ngen"},
                ))
    return results


def _scan_delivery_opt(root: str) -> list[CacheItem]:
    results = []
    do_cache = os.path.join(os.environ.get("WINDIR", win_path("Windows")),
                            "ServiceProfiles", "NetworkService", "AppData",
                            "Local", "Microsoft", "Windows", "DeliveryOptimization", "Cache")
    if os.path.isdir(do_cache):
        sz = dir_total(do_cache)
        if sz > 0:
            results.append(CacheItem(
                path=do_cache, size=sz, provider="win_deep",
                label="Delivery Optimization Cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "delivery_opt", "admin_required": True},
            ))
    return results


def _scan_cleanmgr(root: str) -> list[CacheItem]:
    cleanmgr_path = os.path.join(
        os.environ.get("WINDIR", win_path("Windows")), "System32", "cleanmgr.exe"
    )
    if not os.path.isfile(cleanmgr_path):
        return []
    return [CacheItem(
        path="shell:CleanMgr", size=0, provider="win_deep",
        label="Windows Disk Cleanup (cleanmgr /sageset:1)",
        safety=SafetyLevel.SAFE,
        extra={"type": "cleanmgr", "admin_required": True},
    )]


register("winsxs", _scan_winsxs)
register("windows_old", _scan_windows_old)
register("driver_store", _scan_driver_store)
register("dotnet_ngen_deep", _scan_dotnet_ngen)
register("delivery_opt_deep", _scan_delivery_opt)
register("cleanmgr", _scan_cleanmgr)
