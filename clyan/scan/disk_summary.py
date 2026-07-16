from ..utils.paths import browser_cache_paths
import os
import time
import ctypes
import ctypes.wintypes
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
        t = tb.value; f = fba.value; return t, f, t - f
    except Exception:
        try:
            st = os.statvfs(root)
            t = st.f_frsize * st.f_blocks
            f = st.f_frsize * st.f_bavail
            return t, f, t - f
        except Exception:
            return 0, 0, 0
def _quick_size(path: str) -> int:
    """Sum of immediate file sizes only (no recursion). Fast estimate."""
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
def _walk_dirs(path: str, depth: int, top_n: int = 15, is_top: bool = True) -> list[dict]:
    """Directory tree — bounded-depth dir_total for speed."""
    items = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    if e.name in _SKIP:
                        continue
                    # Top level: bounded depth (3) for fast accurate sizing
                    # Deeper levels: use remaining depth for full accuracy
                    max_walk = 3 if is_top else max(depth + 1, 0)
                    sz = dir_total(e.path, max_depth=max_walk)
                    if sz == 0:
                        continue
                    node = {
                        "name": e.name, "path": e.path,
                        "size": sz, "size_human": format_size(sz),
                    }
                    if depth > 1 and sz >= 100 * 1024 * 1024:
                        children = _walk_dirs(e.path, depth - 1, top_n, is_top=False)
                        if children:
                            node["children"] = children
                    items.append(node)
                except Exception:
                    pass
    except Exception:
        pass
    items.sort(key=lambda x: -x["size"])
    limit = top_n if is_top else min(top_n, 8)
    return items[:limit]
def _classify_usage(name: str) -> str:
    system = {"Windows", "Program Files", "Program Files (x86)", "ProgramData",
              "PerfLogs", "Intel"}
    user = {"Users"}
    recovery = {"$Recycle.Bin", "System Volume Information", "Recovery",
               "Windows.old", "Config.Msi"}
    apps_like = {"mingw64", "Aomei", "temp", "图吧工具箱"}
    if name in system: return "系统"
    if name in user: return "用户数据"
    if name in recovery: return "系统保护/回收"
    if name in apps_like: return "应用/工具"
    if name.startswith("$"): return "系统隐藏"
    return "其他"
def scan_disk(path: str = "C:\\", depth: int = 2, top_n: int = 15) -> ScanResult:
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
    tree = _walk_dirs(path, depth, top_n)
    result.extra["top_dirs"] = tree
    cats: dict[str, int] = {}
    for n in tree:
        c = _classify_usage(n["name"])
        cats[c] = cats.get(c, 0) + n["size"]
    result.extra["categories"] = [
        {"category": k, "total_size": v, "total_size_human": format_size(v)}
        for k, v in sorted(cats.items(), key=lambda x: -x[1])
    ]
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
    result.total_size = used
    result.scan_time_ms = (time.time() - start) * 1000
    _refresh_pulse_cache(path, {"items": [], **result.extra})
    return result