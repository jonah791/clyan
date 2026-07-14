import os
import glob
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total





def _is_admin() -> bool:
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _scan_windows_update(root: str) -> list[CacheItem]:
    results = []
    system32 = os.environ.get("WINDIR", "C:\\Windows")

    sd = os.path.join(system32, "SoftwareDistribution", "Download")
    if os.path.isdir(sd):
        sz = dir_total(sd)
        if sz > 0:
            results.append(CacheItem(
                path=sd, size=sz, provider="windows_system",
                label="Windows Update cache (Download)",
                safety=SafetyLevel.SAFE,
                extra={"type": "windows_update", "admin_required": True},
            ))

    catroot2 = os.path.join(system32, "System32", "catroot2")
    if os.path.isdir(catroot2):
        sz = dir_total(catroot2)
        if sz > 0:
            results.append(CacheItem(
                path=catroot2, size=sz, provider="windows_system",
                label="Windows catroot2 (update signatures)",
                safety=SafetyLevel.SAFE,
                extra={"type": "windows_catroot2", "admin_required": True},
            ))

    return results


def _scan_prefetch(root: str) -> list[CacheItem]:
    results = []
    system32 = os.environ.get("WINDIR", "C:\\Windows")
    pf = os.path.join(system32, "Prefetch")
    if os.path.isdir(pf):
        sz = dir_total(pf)
        if sz >= 1024 * 1024:
            results.append(CacheItem(
                path=pf, size=sz, provider="windows_system",
                label="Windows Prefetch",
                safety=SafetyLevel.SAFE,
                extra={"type": "prefetch"},
            ))
    return results


def _scan_delivery_opt(root: str) -> list[CacheItem]:
    results = []
    do = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "DeliveryOptimization", "Cache")
    if os.path.isdir(do):
        sz = dir_total(do)
        if sz > 0:
            results.append(CacheItem(
                path=do, size=sz, provider="windows_system",
                label="Delivery Optimization cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "delivery_opt"},
            ))
    return results


def _scan_font_cache(root: str) -> list[CacheItem]:
    results = []
    appdata = os.environ.get("LOCALAPPDATA", "")
    fc = os.path.join(appdata, "Microsoft", "Windows", "FontCache")
    if os.path.isdir(fc):
        sz = dir_total(fc)
        if sz > 0:
            results.append(CacheItem(
                path=fc, size=sz, provider="windows_system",
                label="Windows Font Cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "font_cache"},
            ))
    return results


def _scan_recent(root: str) -> list[CacheItem]:
    results = []
    appdata = os.environ.get("APPDATA", "")
    recent = os.path.join(appdata, "Microsoft", "Windows", "Recent")
    if os.path.isdir(recent):
        sz = dir_total(recent)
        if sz > 0:
            results.append(CacheItem(
                path=recent, size=sz, provider="windows_system",
                label="Windows Recent Items",
                safety=SafetyLevel.SAFE,
                extra={"type": "recent_items"},
            ))
    return results


def _scan_thumbnail_cache(root: str) -> list[CacheItem]:
    results = []
    local = os.environ.get("LOCALAPPDATA", "")
    tc = os.path.join(local, "Microsoft", "Windows", "Explorer")
    if os.path.isdir(tc):
        sz = 0
        for f in os.listdir(tc):
            if f.endswith(".db") or "thumbcache" in f.lower():
                fp = os.path.join(tc, f)
                try:
                    sz += os.path.getsize(fp)
                except Exception:
                    pass
        if sz > 0:
            results.append(CacheItem(
                path=tc, size=sz, provider="windows_system",
                label="Windows Thumbnail Cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "thumbnail_cache"},
            ))
    return results


def _scan_dotnet(root: str) -> list[CacheItem]:
    results = []
    system32 = os.environ.get("WINDIR", "C:\\Windows")
    ngen = os.path.join(system32, "assembly", "NativeImages_v*")
    for d in glob.glob(ngen):
        if os.path.isdir(d):
            sz = dir_total(d)
            if sz > 0:
                results.append(CacheItem(
                    path=d, size=sz, provider="windows_system",
                    label=f".NET Native Images ({os.path.basename(d)})",
                    safety=SafetyLevel.SAFE,
                    extra={"type": "dotnet_ngen"},
                ))
    return results


register("windows_update", _scan_windows_update)
register("prefetch", _scan_prefetch)
register("delivery_opt", _scan_delivery_opt)
register("font_cache", _scan_font_cache)
register("recent_items", _scan_recent)
register("thumbnail_cache", _scan_thumbnail_cache)
register("dotnet_ngen", _scan_dotnet)
