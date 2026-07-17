"""Enhanced disk_summary — deep drill-down + invisible directory tracking."""
from ..utils.paths import browser_cache_paths
import os, time, ctypes, ctypes.wintypes
from ..utils.size import format_size
from ..utils.dirtree import dir_total
from ..utils.scanner_base import ScanResult
from ..reflex import _refresh_pulse_cache

_SKIP = {
    "$Recycle.Bin", "System Volume Information", "Recovery",
    "Windows.old", "Config.Msi", "$SysReset", "MSOCache",
    "Boot", "Documents and Settings",
}


def _get_disk_free_space(path: str) -> tuple[int, int, int]:
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    try:
        fba = ctypes.c_ulonglong(0)
        tb = ctypes.c_ulonglong(0)
        tfb = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            root, ctypes.byref(fba), ctypes.byref(tb), ctypes.byref(tfb),
        )
        return tb.value, fba.value, tb.value - fba.value
    except Exception:
        try:
            st = os.statvfs(root)
            return st.f_frsize * st.f_blocks, st.f_frsize * st.f_bavail, 0
        except Exception:
            return 0, 0, 0


def _quick_size(path: str) -> int:
    """Sum of immediate file sizes only (no recursion)."""
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                except Exception:
                    pass
    except Exception:
        pass
    return total


def _scan_tree(path: str, depth: int, top_n: int = 15,
               is_top: bool = True) -> tuple[list[dict], list[str]]:
    """Walk directory tree, return (items, inaccessible).
    
    depth=0 means fully recursive (no limit).
    Inaccessible directories are collected but not included in items.
    """
    items: list[dict] = []
    inaccessible: list[str] = []

    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    if e.name in _SKIP:
                        continue
                    max_walk = 3 if is_top else max(depth, 1) if depth > 0 else -1
                    sz = dir_total(e.path, max_depth=max_walk)
                    if sz == 0:
                        # Might still have deep content — try quick fallback
                        sz = _quick_size(e.path)
                    if sz == 0:
                        continue

                    node = {
                        "name": e.name, "path": e.path,
                        "size": sz, "size_human": format_size(sz),
                    }

                    # Recurse deeper if threshold met
                    recurse = False
                    if depth == 0:  # full recursive
                        recurse = True
                    elif depth > 1 and sz >= 100 * 1024 * 1024:
                        recurse = True

                    if recurse:
                        children, child_inacc = _scan_tree(
                            e.path, max(depth - 1, 0) if depth > 0 else 0,
                            min(top_n, 8), is_top=False)
                        if children:
                            node["children"] = children
                        inaccessible.extend(child_inacc)

                    items.append(node)

                except PermissionError:
                    inaccessible.append(e.path)
                except Exception:
                    pass

    except PermissionError:
        inaccessible.append(path)
        return [], inaccessible
    except Exception:
        pass

    items.sort(key=lambda x: -x["size"])
    limit = top_n if is_top else min(top_n, 8)
    return items[:limit], inaccessible


def _classify_usage(name: str) -> str:
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


def scan_disk(path: str = "C:\\", depth: int = 2, top_n: int = 15) -> ScanResult:
    """Disk usage scan with deep drill-down and inaccessible tracking.
    
    Args:
        path: Drive or directory to scan
        depth: Directory depth (0 = full recursive, 1 = one level, etc.)
        top_n: Max items per level
    """
    start = time.time()
    result = ScanResult()

    total, free, used = _get_disk_free_space(path)
    usage_pct = round(used / total * 100, 1) if total > 0 else 0

    result.extra["disk"] = {
        "path": os.path.splitdrive(os.path.abspath(path))[0] + "\\",
        "total": total, "total_human": format_size(total),
        "used": used, "used_human": format_size(used),
        "free": free, "free_human": format_size(free),
        "usage_percent": usage_pct,
    }

    tree, inaccessible = _scan_tree(path, depth, top_n)
    result.extra["top_dirs"] = tree
    result.extra["inaccessible"] = [
        {"path": p, "reason": "permission denied"}
        for p in inaccessible[:50]
    ]

    # Categories
    cats: dict[str, int] = {}
    for n in tree:
        c = _classify_usage(n["name"])
        cats[c] = cats.get(c, 0) + n["size"]
    result.extra["categories"] = [
        {"category": k, "total_size": v, "total_size_human": format_size(v)}
        for k, v in sorted(cats.items(), key=lambda x: -x[1])
    ]

    # Reclaimable estimate
    garbage_total = 0
    gb: dict[str, int] = {}
    tmp = os.environ.get("TEMP", "")
    if tmp and os.path.isdir(tmp):
        sz = dir_total(tmp)
        if sz > 0:
            garbage_total += sz
            gb["临时文件"] = sz
    for key, label in [("chrome", "Chrome"), ("chrome_code_cache", "Chrome"),
                       ("edge", "Edge"), ("edge_code_cache", "Edge"),
                       ("firefox", "Firefox")]:
        p = browser_cache_paths().get(key, "")
        if p and os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                k = f"{label} 缓存"
                gb[k] = gb.get(k, 0) + sz

    result.extra["reclaimable"] = {
        "total": garbage_total, "total_human": format_size(garbage_total),
        "breakdown": [{"label": k, "size": v, "size_human": format_size(v)}
                      for k, v in sorted(gb.items(), key=lambda x: -x[1])],
    }

    # Account for inaccessible gap
    accounted = sum(n["size"] for n in tree)
    gap = max(0, used - accounted)
    result.extra["gap_size"] = gap
    result.extra["gap_size_human"] = format_size(gap) if gap > 0 else "0"
    result.extra["inaccessible_count"] = len(inaccessible)

    result.total_size = used
    result.scan_time_ms = (time.time() - start) * 1000
    _refresh_pulse_cache(path, {"items": [], **result.extra})
    return result
