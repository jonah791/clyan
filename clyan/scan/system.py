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


def _scan_temp_breakdown() -> list[CacheItem]:
    """Deep-scan Temp to show largest subdirectories inside.

    Identifies known orphan patterns (pip-unpack-*, npm-*, tmp-*)
    left behind by crashed or interrupted processes.
    """
    results = []
    temp = os.environ.get("TEMP", "")
    if not temp or not os.path.isdir(temp):
        return results

    orphan_patterns = ("pip-unpack-", "npm-", "tmp-")
    items = []
    try:
        with os.scandir(temp) as it:
            for e in it:
                try:
                    if not e.is_dir(follow_symlinks=False):
                        continue
                    sz = dir_total(e.path)
                    if sz == 0:
                        continue
                    name = e.name
                    extra: dict = {"type": "temp_subdir"}

                    # Detect known orphan patterns
                    if any(name.startswith(p) for p in orphan_patterns):
                        extra["orphan"] = True
                        extra["orphan_type"] = "pip" if name.startswith("pip-unpack") else "other_tmp"

                    if sz >= 10 * 1024 * 1024:  # Only items >= 10 MB
                        items.append((sz, name, e.path, extra))
                except Exception:
                    pass
    except Exception:
        pass

    items.sort(key=lambda x: -x[0])
    for sz, name, path, extra in items[:15]:
        results.append(CacheItem(
            path=path, size=sz, provider="system_temp_deep",
            label=f"Temp: {name}", safety=DangerLevel.SAFE, extra=extra,
        ))

    return results


class SystemScanner(BaseScanner):
    def __init__(self, deep_temp: bool = True):
        self.deep_temp = deep_temp

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        temp_items = _get_windows_temp()
        for item in temp_items:
            result.items.append(item.to_dict())
            result.total_size += item.size

        # Deep Temp breakdown: largest subdirs inside Temp
        if self.deep_temp:
            for item in _scan_temp_breakdown():
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
