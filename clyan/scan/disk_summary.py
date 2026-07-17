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


def _full_scan_one_pass(path: str, root_drive: str,
                         max_time: float = 150) -> tuple[list[dict], list[dict], list[str], float]:
    """Parallel full scan using ThreadPoolExecutor.
    
    Walks each top-level directory in its own thread.
    Returns (top_dirs, root_files, inaccessible, accounted_size).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _start = time.time()
    dir_sizes: dict[str, int] = {}
    inaccessible: list[str] = []
    fs: list = []

    # Collect top-level dirs
    try:
        for e in os.scandir(root_drive):
            if e.is_dir() and e.name not in _SKIP:
                fs.append(e)
    except Exception:
        pass

    def _walk_one(ep: str) -> tuple[str, int]:
        """Full recursive walk of a single directory."""
        t0 = time.time()
        total = 0
        try:
            for r, _, files in os.walk(ep):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(r, f))
                    except Exception:
                        pass
                if (time.time() - t0) > max_time * 0.7:
                    break
        except Exception:
            pass
        return ep, total

    # Walk each top-level dir in parallel
    with ThreadPoolExecutor(max_workers=min(len(fs), 8)) as pool:
        fut_map = {pool.submit(_walk_one, e.path): e.name for e in fs}
        for f in as_completed(fut_map):
            if (time.time() - _start) > max_time:
                for remaining in fut_map:
                    if not remaining.done():
                        inaccessible.append(f"(timeout: {fut_map[remaining]})")
                break
            try:
                ep, sz = f.result()
                dir_sizes[ep] = sz
            except Exception:
                pass

    # Build results
    top_items = []
    for e in fs:
        sz = dir_sizes.get(e.path, 0)
        if sz > 0:
            top_items.append({
                "name": e.name, "path": e.path,
                "size": sz, "size_human": format_size(sz),
            })

    # Track which dirs were skipped (not walked)
    for e in os.scandir(root_drive):
        if e.is_dir() and e.name not in {x["name"] for x in top_items}:
            if e.name not in _SKIP:
                inaccessible.append(e.path)

    # Root files
    root_file_sizes = {}
    try:
        for e in os.scandir(root_drive):
            if e.is_file():
                try:
                    sz = e.stat().st_size
                    if sz > 10 * 1024 * 1024:
                        root_file_sizes[e.name] = sz
                except:
                    pass
    except:
        pass

    top_items.sort(key=lambda x: -x["size"])
    root_list = [{"name": k, "size": v, "size_human": format_size(v)}
                 for k, v in sorted(root_file_sizes.items(), key=lambda x: -x[1])]
    accounted = sum(x["size"] for x in top_items) + sum(v for v in root_file_sizes.values())
    return top_items[:50], root_list, inaccessible, accounted


def _scan_tree(path: str, depth: int, top_n: int = 15,
               is_top: bool = True) -> tuple[list[dict], list[str]]:
    """Bounded-depth directory tree scan (original mode)."""
    items: list[dict] = []
    inaccessible: list[str] = []

    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    if e.name in _SKIP:
                        inaccessible.append(e.path)
                        continue

                    max_walk = 3 if is_top else max(depth, 1) if depth > 0 else -1
                    sz = dir_total(e.path, max_depth=max_walk)
                    if sz == 0:
                        sz = _quick_size(e.path)
                    if sz == 0:
                        continue

                    node = {
                        "name": e.name, "path": e.path,
                        "size": sz, "size_human": format_size(sz),
                    }

                    if depth > 1 and sz >= 100 * 1024 * 1024:
                        children, child_inacc = _scan_tree(
                            e.path, depth - 1,
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
        full: Force SINGLE-PASS full scan. Walks every file/dir ONCE. 
              Slower (1-2 min) but accounts for ALL space.
    """
    start = time.time()
    result = ScanResult()
    root_drive = os.path.splitdrive(os.path.abspath(path))[0] + "\\"

    total, free, used = _get_disk_free_space(path)

    if full:
        # ── Single-pass full scan ──
        tree, root_files, inaccessible, accounted = _full_scan_one_pass(
            path, root_drive, max_time=120)
        result.extra["full"] = True
        result.extra["accounted_size"] = accounted
        result.extra["accounted_size_human"] = format_size(accounted)
    else:
        # ── Bounded-depth scan ──
        tree, inaccessible = _scan_tree(path, depth, top_n)
        root_files = _account_root_files(root_drive)
        accounted = sum(n["size"] for n in tree) + sum(v["size"] for v in root_files)

    usage_pct = round(used / total * 100, 1) if total > 0 else 0
    result.extra["disk"] = {
        "path": root_drive,
        "total": total, "total_human": format_size(total),
        "used": used, "used_human": format_size(used),
        "free": free, "free_human": format_size(free),
        "usage_percent": usage_pct,
    }
    result.extra["top_dirs"] = tree
    result.extra["root_files"] = root_files

    # Inaccessible
    inaccessible_dirs = [p for p in inaccessible if not p.startswith("(timeout)")]
    had_timeout = any(p.startswith("(timeout)") for p in inaccessible)
    result.extra["inaccessible"] = [
        {"path": p, "reason": "permission denied"}
        for p in inaccessible_dirs[:50]
    ]
    result.extra["inaccessible_count"] = len(inaccessible_dirs)

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
            garbage_total += sz; gb["临时文件"] = sz
    for key, label in [("chrome", "Chrome"), ("chrome_code_cache", "Chrome"),
                       ("edge", "Edge"), ("edge_code_cache", "Edge"),
                       ("firefox", "Firefox")]:
        p = browser_cache_paths().get(key, "")
        if p and os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                k = f"{label} 缓存"; gb[k] = gb.get(k, 0) + sz
    result.extra["reclaimable"] = {
        "total": garbage_total, "total_human": format_size(garbage_total),
        "breakdown": [{"label": k, "size": v, "size_human": format_size(v)}
                      for k, v in sorted(gb.items(), key=lambda x: -x[1])],
    }

    # Gap
    root_file_total = sum(v.get("size", 0) for v in root_files) if root_files else 0
    gap = max(0, used - accounted)
    result.extra["gap_analysis"] = {
        "total_used": used,
        "total_used_human": format_size(used),
        "accounted_total": accounted,
        "accounted_total_human": format_size(accounted),
        "gap": gap,
        "gap_human": format_size(gap),
        "gap_pct": round(gap / max(used, 1) * 100, 1),
        "full_scan_mode": full,
        "timeout": had_timeout,
        "inaccessible_count": len(inaccessible_dirs),
    }
    result.extra["gap_size"] = gap
    result.extra["gap_size_human"] = format_size(gap)

    result.total_size = used
    result.scan_time_ms = (time.time() - start) * 1000
    _refresh_pulse_cache(path, {"items": [], **result.extra})
    return result
