import os
import time
import ctypes
import ctypes.wintypes
from ..utils.size import format_size
from ..utils.scanner_base import ScanResult


def _get_disk_free_space(path: str) -> tuple[int, int, int]:
    """Get total, free, and used bytes for the drive containing *path*.

    Returns (total_bytes, free_bytes, used_bytes).
    Uses Windows GetDiskFreeSpaceExW for accurate values.
    """
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    try:
        free_bytes_available = ctypes.c_ulonglong(0)
        total_bytes = ctypes.c_ulonglong(0)
        total_free_bytes = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            root,
            ctypes.byref(free_bytes_available),
            ctypes.byref(total_bytes),
            ctypes.byref(total_free_bytes),
        )
        total = total_bytes.value
        free = free_bytes_available.value
        used = total - free
        return total, free, used
    except Exception:
        # Fallback: os.statvfs (Unix) or estimate
        try:
            st = os.statvfs(root)
            total = st.f_frsize * st.f_blocks
            free = st.f_frsize * st.f_bavail
            used = total - free
            return total, free, used
        except Exception:
            return 0, 0, 0


def _top_directories(path: str, top_n: int = 15) -> list[dict]:
    """List the largest immediate child directories of *path* using dir_total.

    Skips system-protected dirs (same list as SpaceScanner._SKIP_DIRS).
    """
    skip = {
        "$Recycle.Bin", "System Volume Information", "Recovery",
        "Windows.old", "Config.Msi", "$SysReset", "MSOCache",
        "Boot", "Documents and Settings",
    }
    from ..utils.dirtree import dir_total

    items = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        name = e.name
                        if name in skip:
                            continue
                        # Use dir_total (cached, fast)
                        total_size = 0
                        try:
                            total_size = dir_total(e.path)
                        except Exception:
                            pass
                        items.append({
                            "path": e.path,
                            "size": total_size,
                            "name": name,
                        })
                except Exception:
                    pass
    except Exception:
        pass

    items.sort(key=lambda x: -x["size"])
    return items[:top_n]


def _classify_usage(name: str) -> str:
    """Classify a top-level directory into a category."""
    system = {"Windows", "Program Files", "Program Files (x86)", "ProgramData",
              "PerfLogs", "Intel"}
    user = {"Users"}
    recovery = {"$Recycle.Bin", "System Volume Information", "Recovery",
               "Windows.old", "Config.Msi"}
    apps_like = {"mingw64", "Aomei", "temp", "图吧工具箱"}
    if name in system:
        return "系统"
    if name in user:
        return "用户数据"
    if name in recovery:
        return "系统保护/回收"
    if name in apps_like:
        return "应用/工具"
    if name.startswith("$"):
        return "系统隐藏"
    return "其他"


def scan_disk(path: str = "C:\\", top_n: int = 15) -> ScanResult:
    """Scan disk usage: capacity info + top directories + garbage estimate.

    Returns a ScanResult with extra fields for disk overview.
    """
    start = time.time()
    result = ScanResult()

    # 1. Disk capacity
    total, free, used = _get_disk_free_space(path)
    usage_pct = round(used / total * 100, 1) if total > 0 else 0

    result.extra["disk"] = {
        "path": os.path.splitdrive(os.path.abspath(path))[0] + "\\",
        "total": total,
        "total_human": format_size(total),
        "used": used,
        "used_human": format_size(used),
        "free": free,
        "free_human": format_size(free),
        "usage_percent": usage_pct,
    }

    # 2. Top-level directory breakdown (skip protected system dirs)
    dirs = _top_directories(path, top_n)
    categories: dict[str, int] = {}
    for d in dirs:
        cat = _classify_usage(d["name"])
        categories[cat] = categories.get(cat, 0) + d["size"]

    result.extra["top_dirs"] = dirs
    result.extra["categories"] = [
        {"category": cat, "total_size": sz, "total_size_human": format_size(sz)}
        for cat, sz in sorted(categories.items(), key=lambda x: -x[1])
    ]

    # 3. Run a lightweight garbage scan to estimate reclaimable space
    #    (Temp + browser caches — the fast, safe items)
    garbage_total = 0
    garbage_breakdown = {}

    # Temp
    temp = os.environ.get("TEMP", "")
    if temp and os.path.isdir(temp):
        from ..utils.dirtree import dir_total
        temp_sz = dir_total(temp)
        if temp_sz > 0:
            garbage_total += temp_sz
            garbage_breakdown["临时文件"] = temp_sz

    # Browser caches
    from ..utils.paths import browser_cache_paths
    bpaths = browser_cache_paths()
    for key, label in [("chrome", "Chrome"), ("chrome_code_cache", "Chrome"),
                       ("edge", "Edge"), ("edge_code_cache", "Edge"),
                       ("firefox", "Firefox")]:
        p = bpaths.get(key, "")
        if p and os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                garbage_total += sz
                garbage_breakdown[f"{label} 缓存"] = \
                    garbage_breakdown.get(f"{label} 缓存", 0) + sz

    result.extra["reclaimable"] = {
        "total": garbage_total,
        "total_human": format_size(garbage_total),
        "breakdown": [
            {"label": k, "size": v, "size_human": format_size(v)}
            for k, v in sorted(garbage_breakdown.items(), key=lambda x: -x[1])
        ],
    }

    result.total_size = used
    result.scan_time_ms = (time.time() - start) * 1000
    return result
