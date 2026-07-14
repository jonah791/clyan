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


class SystemScanner(BaseScanner):
    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        temp_items = _get_windows_temp()
        for item in temp_items:
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
