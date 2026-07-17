"""Enhanced disk_summary — deep drill-down + invisible directory tracking + gap analysis."""
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

# System files at drive root that consume significant space
_SYSTEM_ROOT_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys"}


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
               full: bool = False, is_top: bool = True,
               max_time: float | None = None,
               _start: float | None = None) -> tuple[list[dict], list[str]]:
    """Walk directory tree, return (items, inaccessible).
    
    full=True: force full recursion, auto-dive into every dir > 500 MB.
    depth=0: fully recursive (no limit) — classic mode.
    max_time: soft timeout in seconds.
    """
    if _start is None:
        _start = time.time()
    items: list[dict] = []
    inaccessible: list[str] = []

    try:
        with os.scandir(path) as it:
            for e in it:
                if max_time and (time.time() - _start) > max_time:
                    inaccessible.append("(timeout)")
                    break
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    if e.name in _SKIP:
                        inaccessible.append(e.path)
                        continue

                    # Determine recursion depth for dir_total
                    if full:
                        max_walk = -1  # fully recursive
                    elif is_top:
                        max_walk = 3  # top level: 3 levels deep
                    else:
                        max_walk = max(depth, 1) if depth > 0 else -1

                    sz = dir_total(e.path, max_depth=max_walk)
                    if sz == 0:
                        sz = _quick_size(e.path)
                    if sz == 0:
                        continue

                    node = {
                        "name": e.name, "path": e.path,
                        "size": sz, "size_human": format_size(sz),
                    }

                    # Recurse deeper
                    recurse = False
                    if full and sz >= 500 * 1024 * 1024:
                        recurse = True
                    elif depth == 0:
                        recurse = True
                    elif depth > 1 and sz >= 100 * 1024 * 1024:
                        recurse = True

                    if recurse:
                        children, child_inacc = _scan_tree(
                            e.path, max(depth - 1, 0) if depth > 0 else 0,
                            min(top_n, 8), full=full, is_top=False,
                            max_time=max_time, _start=_start)
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


def _account_root_files(root: str) -> dict:
    """Measure system files at drive root."""
    accounted: dict[str, int] = {}
    for name in _SYSTEM_ROOT_FILES:
        fp = os.path.join(root, name)
        try:
            if os.path.isfile(fp):
                sz = os.path.getsize(fp)
                accounted[name] = sz
        except Exception:
            pass
    # Also scan for any other >100 MB files at root
    try:
        for e in os.scandir(root):
            if e.is_file() and e.name not in _SYSTEM_ROOT_FILES:
                try:
                    sz = e.stat().st_size
                    if sz > 100 * 1024 * 1024:  # >100 MB
                        accounted[e.name] = sz
                except Exception:
                    pass
    except Exception:
        pass
    return accounted


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


def scan_disk(path: str = "C:\\", depth: int = 2, top_n: int = 15,
              full: bool = False) -> ScanResult:
    """Disk usage scan with deep drill-down, inaccessible tracking, and gap analysis.
    
    Args:
        path: Drive or directory to scan
        depth: Directory depth (0 = full recursive, 1 = one level, etc.)
        top_n: Max items per level
        full: Force full recursion into all large directories (>500 MB)
              Uses dir_total(-1) for accurate sizing of each node.
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

    # Scan tree
    max_time = 120 if full else None  # 2 min soft timeout for full scan
    tree, inaccessible = _scan_tree(path, depth, top_n, full=full,
                                     max_time=max_time, _start=start)
    result.extra["top_dirs"] = tree

    # Track inaccessible dirs
    inaccessible_dirs = [p for p in inaccessible if p != "(timeout)"]
    had_timeout = "(timeout)" in inaccessible
    result.extra["inaccessible"] = [
        {"path": p, "reason": "permission denied"}
        for p in inaccessible_dirs[:50]
    ]

    # System root files
    root_drive = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    root_files = _account_root_files(root_drive)
    result.extra["root_files"] = [
        {"name": k, "size": v, "size_human": format_size(v)}
        for k, v in sorted(root_files.items(), key=lambda x: -x[1])
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

    # Gap analysis
    accounted = sum(n["size"] for n in tree) + sum(v for v in root_files.values())
    gap = max(0, used - accounted)
    inaccessible_known = sum(
        os.path.getsize(os.path.join(root_drive, d))
        for d in ["$Recycle.Bin", "System Volume Information"]
        if os.path.isdir(os.path.join(root_drive, d))
    )
    result.extra["gap_analysis"] = {
        "total_used": used,
        "total_used_human": format_size(used),
        "accounted_dirs": sum(n["size"] for n in tree),
        "accounted_dirs_human": format_size(sum(n["size"] for n in tree)),
        "accounted_root_files": sum(v for v in root_files.values()),
        "accounted_root_files_human": format_size(sum(v for v in root_files.values())),
        "gap": gap,
        "gap_human": format_size(gap),
        "gap_pct": round(gap / max(used, 1) * 100, 1),
        "breakdown": {
            "system_protected_estimate": min(gap, inaccessible_known),
            "depth_limited": max(0, gap - inaccessible_known) if not full else 0,
            "timeout": had_timeout,
        },
    }
    result.extra["gap_size"] = gap
    result.extra["gap_size_human"] = format_size(gap)
    result.extra["inaccessible_count"] = len(inaccessible_dirs)

    result.total_size = used
    result.scan_time_ms = (time.time() - start) * 1000
    _refresh_pulse_cache(path, {"items": [], **result.extra})
    return result
