import os
import time
import ctypes
from ..utils.scanner_base import ScanResult, BaseScanner
from ..utils.dirtree import dir_total
from ..core.config import DangerLevel
from .providers import CacheItem


def _get_recycle_bin_size() -> int:
    try:
        if os.name == "nt":
            class SHQUERYRBINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.wintypes.DWORD),
                    ("i64Size", ctypes.c_int64),
                    ("i64NumItems", ctypes.c_int64),
                ]
            SHQueryRecycleBin = ctypes.windll.shell32.SHQueryRecycleBinW
            SHQueryRecycleBin.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.POINTER(SHQUERYRBINFO)]
            SHQueryRecycleBin.restype = ctypes.HRESULT
            rbi = SHQUERYRBINFO()
            rbi.cbSize = ctypes.sizeof(SHQUERYRBINFO)
            hr = SHQueryRecycleBin(None, ctypes.byref(rbi))
            if hr == 0:
                return rbi.i64Size
    except Exception:
        pass
    return 0


def _get_windows_temp() -> list[CacheItem]:
    results = []
    seen = set()
    for var in ["TEMP", "TMP", "WINDIR"]:
        p = os.environ.get(var, "")
        if var == "WINDIR":
            p = os.path.join(p, "Temp")
        if p and os.path.isdir(p):
            norm = os.path.normpath(p)
            if norm not in seen:
                seen.add(norm)
                try:
                    sz = dir_total(norm)
                    if sz > 0:
                        results.append(CacheItem(
                            path=norm, size=sz, provider="system",
                            label=f"Windows Temp ({os.path.basename(norm)})",
                            safety=DangerLevel.SAFE,
                            extra={"type": "system_temp"},
                        ))
                except Exception:
                    pass
    return results


# Expanded orphan prefixes — matches confidence.py
_ORPHAN_PREFIXES = ("pip-unpack-", "npm-", "tmp-", "conda-", "msi-", "vs_")


def _scan_temp_breakdown(depth: int = 2) -> list[CacheItem]:
    """Recursively scan Temp for largest subdirectories and orphan temp dirs.

    *depth=1* scans only direct children.
    *depth=2* (default) also checks inside orphan / large dirs.
    """
    results = []
    temp = os.environ.get("TEMP", "")
    if not temp or not os.path.isdir(temp):
        return results

    def _scan_dir(parent: str, current_depth: int) -> list[CacheItem]:
        items = []
        try:
            with os.scandir(parent) as it:
                for e in it:
                    try:
                        if not e.is_dir(follow_symlinks=False):
                            continue
                        name = e.name
                        sz = dir_total(e.path)
                        if sz == 0:
                            continue
                        extra: dict = {"type": "temp_subdir"}
                        is_orphan = any(name.startswith(p) for p in _ORPHAN_PREFIXES)
                        if is_orphan:
                            extra["orphan"] = True
                            # Classify orphan type
                            if name.startswith("pip-unpack"):
                                extra["orphan_type"] = "pip"
                            elif name.startswith("npm-"):
                                extra["orphan_type"] = "npm"
                            elif name.startswith("conda-"):
                                extra["orphan_type"] = "conda"
                            elif name.startswith("tmp-"):
                                extra["orphan_type"] = "tmp"
                            else:
                                extra["orphan_type"] = "installer"
                        # Recurse into orphan dirs or large dirs at depth 1
                        if current_depth < depth and (is_orphan or sz >= 100 * 1024 * 1024):
                            children = _scan_dir(e.path, current_depth + 1)
                            if children:
                                extra["children"] = [c.to_dict() for c in children]
                        if sz >= 10 * 1024 * 1024:
                            items.append(CacheItem(
                                path=e.path, size=sz,
                                provider="system_temp_deep",
                                label=f"Temp: {name}",
                                safety=DangerLevel.SAFE,
                                extra=extra,
                            ))
                    except Exception:
                        pass
        except Exception:
            pass
        items.sort(key=lambda x: -x.size)
        return items[:15]

    return _scan_dir(temp, 1)


class SystemScanner(BaseScanner):
    def __init__(self, deep_temp: bool = True, temp_depth: int = 2):
        self.deep_temp = deep_temp
        self.temp_depth = temp_depth

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        temp_items = _get_windows_temp()
        for item in temp_items:
            result.items.append(item.to_dict())
            result.total_size += item.size

        # Deep Temp breakdown: largest subdirs inside Temp
        if self.deep_temp:
            for item in _scan_temp_breakdown(depth=self.temp_depth):
                result.items.append(item.to_dict())
                result.total_size += item.size

        try:
            rb_size = _get_recycle_bin_size()
            if rb_size > 0:
                item = CacheItem(
                    path="shell:RecycleBinFolder",
                    size=rb_size, provider="system",
                    label="Recycle Bin",
                    safety=DangerLevel.SAFE,
                    extra={"type": "recycle_bin"},
                )
                result.items.append(item.to_dict())
                result.total_size += rb_size
        except Exception:
            pass

        result.items.sort(key=lambda x: x["size"], reverse=True)
        result.item_count = len(result.items)
        result.scan_time_ms = (time.time() - start) * 1000
        return result
