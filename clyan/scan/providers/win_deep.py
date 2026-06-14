import os
import subprocess
import glob
from . import CacheItem, SafetyLevel, register


def _dir_total(path: str) -> int:
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                    elif e.is_dir(follow_symlinks=False):
                        total += _dir_total(e.path)
                except Exception:
                    pass
    except Exception:
        pass
    return total


def _scan_winsxs(root: str) -> list[CacheItem]:
    results = []
    windir = os.environ.get("WINDIR", "C:\\Windows")
    winsxs = os.path.join(windir, "WinSxS")

    if os.path.isdir(winsxs):
        try:
            sz = _dir_total(winsxs)
            if sz > 0:
                result = subprocess.run(
                    ["dism", "/online", "/Cleanup-Image", "/AnalyzeComponentStore",
                     "/english"],
                    capture_output=True, text=True, timeout=120
                )
                reclaimable = 0
                for line in result.stdout.splitlines():
                    if "reclaimable" in line.lower():
                        import re
                        m = re.search(r"([\d.]+)\s*(MB|GB)", line)
                        if m:
                            val = float(m.group(1))
                            unit = m.group(2)
                            reclaimable = int(val * (1024**3 if unit == "GB" else 1024**2))
                            break
                results.append(CacheItem(
                    path=winsxs, size=sz, provider="win_deep",
                    label=f"WinSxS (component store, {sz/(1024**3):.1f} GB, ~{reclaimable/(1024**3):.1f} GB reclaimable)",
                    safety=SafetyLevel.SAFE,
                    extra={"type": "winsxs", "reclaimable": reclaimable, "admin_required": True},
                ))
        except Exception:
            results.append(CacheItem(
                path=winsxs, size=sz, provider="win_deep",
                label=f"WinSxS (component store, {sz/(1024**3):.1f} GB)",
                safety=SafetyLevel.SAFE,
                extra={"type": "winsxs", "admin_required": True},
            ))

    return results


def _scan_windows_old(root: str) -> list[CacheItem]:
    results = []
    win_old = "C:\\Windows.old"
    if os.path.isdir(win_old):
        sz = _dir_total(win_old)
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
    windir = os.environ.get("WINDIR", "C:\\Windows")
    drv = os.path.join(windir, "System32", "DriverStore", "FileRepository")
    if os.path.isdir(drv):
        sz = _dir_total(drv)
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
    windir = os.environ.get("WINDIR", "C:\\Windows")
    for asm_dir in glob.glob(os.path.join(windir, "assembly", "NativeImages_v*")):
        if os.path.isdir(asm_dir):
            sz = _dir_total(asm_dir)
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
    do_cache = os.path.join(os.environ.get("WINDIR", "C:\\Windows"),
                            "ServiceProfiles", "NetworkService", "AppData",
                            "Local", "Microsoft", "Windows", "DeliveryOptimization", "Cache")
    if os.path.isdir(do_cache):
        sz = _dir_total(do_cache)
        if sz > 0:
            results.append(CacheItem(
                path=do_cache, size=sz, provider="win_deep",
                label="Delivery Optimization Cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "delivery_opt", "admin_required": True},
            ))
    return results


def _scan_cleanmgr(root: str) -> list[CacheItem]:
    results = []
    try:
        r = subprocess.run(["cleanmgr", "/sagerun:1"], capture_output=True, text=True, timeout=10)
    except Exception:
        pass
    results.append(CacheItem(
        path="shell:CleanMgr", size=0, provider="win_deep",
        label="Windows Disk Cleanup (cleanmgr /sageset:1)",
        safety=SafetyLevel.SAFE,
        extra={"type": "cleanmgr", "admin_required": True},
    ))
    return results


register("winsxs", _scan_winsxs)
register("windows_old", _scan_windows_old)
register("driver_store", _scan_driver_store)
register("dotnet_ngen_deep", _scan_dotnet_ngen)
register("delivery_opt_deep", _scan_delivery_opt)
register("cleanmgr", _scan_cleanmgr)
