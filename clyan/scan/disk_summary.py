"""Enhanced disk_summary — deep drill-down + invisible directory tracking + gap analysis + --clean."""
from ..utils.paths import browser_cache_paths
import os, time, ctypes, ctypes.wintypes, sys
from ..utils.size import format_size
from ..utils.dirtree import dir_total
from ..utils.scanner_base import ScanResult
from ..reflex import _refresh_pulse_cache

_SKIP = {
    "$Recycle.Bin", "System Volume Information", "Recovery",
    "Windows.old", "Config.Msi", "$SysReset", "MSOCache",
    "Boot", "Documents and Settings",
}
_SYSTEM_ROOT_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys"}


# ── Privilege ──────────────────────────────────────────

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def _try_enable_privilege(privilege_name: str) -> bool:
    try:
        class LUID(ctypes.Structure):
            _fields_ = [("LowPart", ctypes.c_ulong), ("HighPart", ctypes.c_long)]
        class TOKEN_PRIVILEGES(ctypes.Structure):
            _fields_ = [("PrivilegeCount", ctypes.c_ulong), ("Luid", LUID), ("Attributes", ctypes.c_ulong)]
        TOKEN_ADJUST_PRIVILEGES = 0x0020
        TOKEN_QUERY = 0x0008
        token = ctypes.wintypes.HANDLE()
        ctypes.windll.advapi32.OpenProcessToken(
            ctypes.windll.kernel32.GetCurrentProcess(),
            TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token))
        luid = LUID()
        ctypes.windll.advapi32.LookupPrivilegeValueW(None, privilege_name, ctypes.byref(luid))
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Luid = luid
        tp.Attributes = 0x00000002
        result = ctypes.windll.advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
        ctypes.windll.kernel32.CloseHandle(token)
        return result != 0
    except Exception:
        return False


def ensure_scan_privileges() -> tuple[bool, str]:
    if is_admin():
        if _try_enable_privilege("SeBackupPrivilege"):
            return True, "Administrator + SeBackupPrivilege enabled"
        return True, "Administrator (limited by ACL)"
    if _try_enable_privilege("SeBackupPrivilege"):
        return True, "SeBackupPrivilege enabled (limited)"
    return False, "Not running as administrator. Use --elevate to gain full access."


# ── Helpers ────────────────────────────────────────────

def _get_disk_free_space(path: str) -> tuple[int, int, int]:
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    try:
        fba = ctypes.c_ulonglong(0)
        tb = ctypes.c_ulonglong(0)
        tfb = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            root, ctypes.byref(fba), ctypes.byref(tb), ctypes.byref(tfb))
        return tb.value, fba.value, tb.value - fba.value
    except Exception:
        try:
            st = os.statvfs(root)
            return st.f_frsize * st.f_blocks, st.f_frsize * st.f_bavail, 0
        except Exception:
            return 0, 0, 0


def _quick_size(path: str) -> int:
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


def _get_recycle_bin_size() -> int:
    try:
        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
        ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
        return info.i64Size
    except Exception:
        return 0


def _probe_protected_dirs(root_drive: str) -> dict[str, int]:
    results = {}
    rb_size = _get_recycle_bin_size()
    if rb_size > 0:
        results["$Recycle.Bin"] = rb_size
    for name in ["System Volume Information", "Boot", "Recovery",
                 "$Windows.~WS", "Config.Msi", "$SysReset"]:
        if os.path.isdir(os.path.join(root_drive, name)):
            results[name] = 0
    return results


def _classify_usage(name: str) -> str:
    system = {"Windows", "Program Files", "Program Files (x86)", "ProgramData", "PerfLogs", "Intel"}
    user = {"Users"}
    recovery = {"$Recycle.Bin", "System Volume Information", "Recovery", "Windows.old", "Config.Msi"}
    apps_like = {"mingw64", "Aomei", "temp", "图吧工具箱"}
    if name in system: return "系统"
    if name in user: return "用户数据"
    if name in recovery: return "系统保护/回收"
    if name in apps_like: return "应用/工具"
    if name.startswith("$"): return "系统隐藏"
    return "其他"


# ── Garbage classification patterns ────────────────────

_GARBAGE_SUBSTRINGS = {
    "__pycache__", "_cacache", "npm-cache", "yarn/cache", "yarn/cache",
    "pip/cache", "pip/wheels", ".bun/cache",
    "go/build", "go-build", "go/pkg/mod", ".rustup/downloads",
    ".cargo/registry/cache", "nuget/cache",
    "chrome/user data/default/cache", "chrome/user data/default/code cache",
    "edge/user data/default/cache", "edge/user data/default/code cache",
    "chromium/user data/default/cache", "chromium/user data/default/code cache",
    "firefox/profiles",
    "appdata/local/temp", "windows/prefetch",
    "huggingface/cache", "ollama/models/blobs",
    "thumbcache", "iconcache",
    "target/debug", "target/release", "target/incremental",
    ".gradle/caches", ".m2/repository",
    ".vs/", ".git/objects",
    "miniconda3/pkgs", "crashdumps",
    "potupdate", "electron/cache", "platformprocess/cache",
    "proton_mail/packages", "updater/pending",
}


def _classify_dir(path: str) -> bool:
    """Directory-level garbage classification. Returns True if path is disposable cache."""
    lower = path.lower().replace("\\", "/")
    for sub in _GARBAGE_SUBSTRINGS:
        if sub in lower:
            return True
    return False


# ── Scan tree (bounded depth) ──────────────────────────

def _scan_tree(path: str, depth: int, top_n: int = 15,
               is_top: bool = True,
               classify_garbage: bool = False) -> tuple[list[dict], list[str]]:
    items = []
    inaccessible = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False): continue
                    if e.name in _SKIP:
                        inaccessible.append(e.path)
                        continue
                    max_walk = 3 if is_top else max(depth, 1) if depth > 0 else -1
                    sz = dir_total(e.path, max_depth=max_walk)
                    if sz == 0: sz = _quick_size(e.path)
                    if sz == 0: continue
                    node = {"name": e.name, "path": e.path, "size": sz, "size_human": format_size(sz)}
                    if classify_garbage:
                        is_garbage = _classify_dir(e.path)
                        cln = sz if is_garbage else 0
                        node["cleanable"] = cln
                        node["cleanable_human"] = format_size(cln) if cln > 0 else "0"
                        node["cleanable_pct"] = round(cln / max(sz, 1) * 100, 1) if cln > 0 else 0
                    if depth > 1 and sz >= 100 * 1024 * 1024:
                        children, child_inacc = _scan_tree(e.path, depth - 1, min(top_n, 8), is_top=False, classify_garbage=classify_garbage)
                        if children: node["children"] = children
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
    return items[:top_n if is_top else min(top_n, 8)], inaccessible


# ── Full scan (parallel) ───────────────────────────────

def _full_scan_one_pass(path: str, root_drive: str,
                         max_time: float = 150,
                         classify_garbage: bool = False) -> tuple[list[dict], list[dict], list[str], float]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    _start = time.time()
    dir_sizes: dict[str, int] = {}
    inaccessible: list[str] = []
    fs: list = []
    have_backup = _try_enable_privilege("SeBackupPrivilege")
    skip_set = set() if have_backup else _SKIP
    try:
        for e in os.scandir(root_drive):
            if e.is_dir() and e.name not in skip_set:
                fs.append(e)
            elif e.is_dir() and e.name in skip_set:
                if have_backup:
                    try: next(os.scandir(e.path), None); fs.append(e)
                    except Exception: inaccessible.append(e.path)
                else: inaccessible.append(e.path)
    except Exception:
        pass

    def walk_one(ep: str) -> tuple[str, int]:
        t0 = time.time()
        total = 0
        try:
            for r, _, files in os.walk(ep):
                for f in files:
                    try: total += os.path.getsize(os.path.join(r, f))
                    except Exception: pass
                if (time.time() - t0) > max_time * 0.7: break
        except Exception:
            pass
        return ep, total

    with ThreadPoolExecutor(max_workers=min(len(fs), 8)) as pool:
        fut_map = {pool.submit(walk_one, e.path): e.name for e in fs}
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

    # Build results with directory-level garbage classification
    top_items = []
    for e in fs:
        sz = dir_sizes.get(e.path, 0)
        if sz > 0:
            node = {"name": e.name, "path": e.path, "size": sz, "size_human": format_size(sz)}
            if classify_garbage:
                is_garbage = _classify_dir(e.path)
                cln = sz if is_garbage else 0
                node["cleanable"] = cln
                node["cleanable_human"] = format_size(cln) if cln > 0 else "0"
                node["cleanable_pct"] = round(cln / max(sz, 1) * 100, 1) if cln > 0 else 0
            top_items.append(node)

    # Track skipped dirs
    for e in os.scandir(root_drive):
        if e.is_dir() and e.name not in {x["name"] for x in top_items}:
            if e.name not in _SKIP: inaccessible.append(e.path)

    # Root files
    root_file_sizes = {}
    try:
        for e in os.scandir(root_drive):
            if e.is_file():
                try:
                    sz = e.stat().st_size
                    if sz > 10 * 1024 * 1024: root_file_sizes[e.name] = sz
                except Exception: pass
    except Exception: pass

    top_items.sort(key=lambda x: -x["size"])
    root_list = [{"name": k, "size": v, "size_human": format_size(v)} for k, v in sorted(root_file_sizes.items(), key=lambda x: -x[1])]
    accounted = sum(x["size"] for x in top_items) + sum(v for v in root_file_sizes.values())
    return top_items[:50], root_list, inaccessible, accounted


# ── Main entry ─────────────────────────────────────────

def scan_disk(path: str = "C:\\", depth: int = 2, top_n: int = 15,
              full: bool = False, clean: bool = False) -> ScanResult:
    """Disk usage scan with deep drill-down, gap analysis, and optional garbage classification.

    Args:
        path: Drive or directory to scan
        depth: Directory depth (0 = full recursive)
        top_n: Max items per level
        full: Single-pass full scan (covers more space, slower)
        clean: Classify directories as garbage/not-garbage by path patterns
    """
    start = time.time()
    result = ScanResult()
    root_drive = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    total, free, used = _get_disk_free_space(path)

    if full:
        tree, root_files, inaccessible, accounted = _full_scan_one_pass(
            path, root_drive, max_time=120, classify_garbage=clean)
        result.extra["full"] = True
        result.extra["accounted_size"] = accounted
        result.extra["accounted_size_human"] = format_size(accounted)
    else:
        tree, inaccessible = _scan_tree(path, depth, top_n, classify_garbage=clean)
        root_files_raw = {}
        for name in _SYSTEM_ROOT_FILES:
            fp = os.path.join(root_drive, name)
            try:
                if os.path.isfile(fp): root_files_raw[name] = os.path.getsize(fp)
            except Exception: pass
        root_files = [{"name": k, "size": v, "size_human": format_size(v)} for k, v in sorted(root_files_raw.items(), key=lambda x: -x[1])]
        accounted = sum(n["size"] for n in tree) + sum(v.get("size", 0) for v in root_files)

    usage_pct = round(used / total * 100, 1) if total > 0 else 0
    result.extra["disk"] = {
        "path": root_drive, "total": total, "total_human": format_size(total),
        "used": used, "used_human": format_size(used),
        "free": free, "free_human": format_size(free), "usage_percent": usage_pct,
    }
    result.extra["top_dirs"] = tree
    result.extra["root_files"] = root_files

    inaccessible_dirs = [p for p in inaccessible if not p.startswith("(timeout)")]
    had_timeout = any(p.startswith("(timeout)") for p in inaccessible)
    result.extra["inaccessible"] = [{"path": p, "reason": "permission denied"} for p in inaccessible_dirs[:50]]
    result.extra["inaccessible_count"] = len(inaccessible_dirs)

    cats = {}
    for n in tree:
        c = _classify_usage(n["name"])
        cats[c] = cats.get(c, 0) + n["size"]
    result.extra["categories"] = [
        {"category": k, "total_size": v, "total_size_human": format_size(v)}
        for k, v in sorted(cats.items(), key=lambda x: -x[1])
    ]

    # Reclaimable estimate
    garbage_total = 0
    gb = {}
    tmp = os.environ.get("TEMP", "")
    if tmp and os.path.isdir(tmp):
        sz = dir_total(tmp)
        if sz > 0: garbage_total += sz; gb["临时文件"] = sz
    for key, label in [("chrome", "Chrome"), ("chrome_code_cache", "Chrome"),
                       ("edge", "Edge"), ("edge_code_cache", "Edge"), ("firefox", "Firefox")]:
        p = browser_cache_paths().get(key, "")
        if p and os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0: k = f"{label} 缓存"; gb[k] = gb.get(k, 0) + sz
    result.extra["reclaimable"] = {
        "total": garbage_total, "total_human": format_size(garbage_total),
        "breakdown": [{"label": k, "size": v, "size_human": format_size(v)} for k, v in sorted(gb.items(), key=lambda x: -x[1])],
    }

    # Gap
    protected = _probe_protected_dirs(root_drive)
    protected_total = sum(protected.values())
    gap = max(0, used - accounted - protected_total)
    result.extra["protected_dirs"] = [
        {"name": k, "size": v, "size_human": format_size(v), "note": "needs admin" if v == 0 and k != "$Recycle.Bin" else ""}
        for k, v in sorted(protected.items(), key=lambda x: -x[1])
    ]
    result.extra["gap_analysis"] = {
        "total_used": used, "total_used_human": format_size(used),
        "accounted_total": accounted, "accounted_total_human": format_size(accounted),
        "gap": gap, "gap_human": format_size(gap), "gap_pct": round(gap / max(used, 1) * 100, 1),
        "full_scan_mode": full, "timeout": had_timeout,
        "inaccessible_count": len(inaccessible_dirs),
    }
    result.extra["gap_size"] = gap
    result.extra["gap_size_human"] = format_size(gap)

    result.total_size = used
    result.scan_time_ms = (time.time() - start) * 1000
    _refresh_pulse_cache(path, {"items": [], **result.extra})
    return result
