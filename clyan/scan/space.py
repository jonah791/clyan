import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..utils.scanner_base import ScanResult, BaseScanner
from ..utils.dirtree import dir_total


# Directories that SpaceScanner should NOT walk into (uses dir_total for quick size).
_SKIP_DIRS = {
    "$Recycle.Bin", "System Volume Information", "Recovery",
    "Windows.old", "Config.Msi", "$SysReset", "MSOCache",
    "Windows", "Program Files", "Program Files (x86)", "ProgramData",
    "PerfLogs", "Intel",
}


def _scan_one(path: str, max_depth: int, current_depth: int) -> tuple[list, int]:
    results: list[dict] = []
    total = 0
    try:
        with os.scandir(path) as it:
            entries = list(it)
    except Exception:
        return results, total

    dirs_to_size: list[tuple[str, str]] = []      # (name, fullpath) → dir_total in parallel
    dirs_to_recurse: list[tuple[str, str]] = []    # (name, fullpath) → recurse into
    file_entries: list[tuple[str, int]] = []       # (name, size)

    for e in entries:
        try:
            if e.is_dir(follow_symlinks=False):
                name = e.name
                if current_depth <= 1 and name in _SKIP_DIRS:
                    dirs_to_size.append((name, e.path))
                elif current_depth >= max_depth:
                    dirs_to_size.append((name, e.path))
                else:
                    dirs_to_recurse.append((name, e.path))
            else:
                s = e.stat().st_size
                total += s
                file_entries.append((e.name, s))
        except Exception:
            pass

    # Parallel dir_total for leaf directories
    if dirs_to_size:
        n = min(8, len(dirs_to_size))
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = {pool.submit(dir_total, fp): (name, fp) for name, fp in dirs_to_size}
            for f in as_completed(futures):
                name, fp = futures[f]
                try:
                    sz = f.result()
                except Exception:
                    sz = 0
                total += sz
                results.append({"path": fp, "size": sz, "is_dir": True})

    # Recurse deeper
    for name, fp in dirs_to_recurse:
        try:
            sub, sub_sz = _scan_one(fp, max_depth, current_depth + 1)
            total += sub_sz
            results.append({"path": fp, "size": sub_sz, "is_dir": True, "children": sub})
        except Exception:
            pass

    for name, sz in file_entries:
        results.append({
            "path": os.path.join(path, name), "size": sz, "is_dir": False,
        })

    return results, total


class SpaceScanner(BaseScanner):
    def __init__(self, path: str, max_depth: int = 2, min_size: int = 0, top_n: int = 50):
        self.path = path
        self.max_depth = max_depth
        self.min_size = min_size
        self.top_n = top_n

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        if not os.path.exists(self.path):
            result.errors.append(f"path not found: {self.path}")
            result.scan_time_ms = (time.time() - start) * 1000
            return result

        try:
            entries = [os.path.join(self.path, f) for f in os.listdir(self.path)]
        except Exception as e:
            result.errors.append(f"cannot list dir: {e}")
            result.scan_time_ms = (time.time() - start) * 1000
            return result

        if not entries:
            result.scan_time_ms = (time.time() - start) * 1000
            return result

        n_workers = min(8, len(entries))

        all_parts = []
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_scan_one, p, self.max_depth, 1): p for p in entries}
            for f in as_completed(futures):
                try:
                    all_parts.append(f.result())
                except Exception:
                    pass

        merged = []
        total = 0
        for sub_res, sub_sz in all_parts:
            merged.extend(sub_res)
            total += sub_sz

        merged.sort(key=lambda x: x.get("size", 0), reverse=True)
        result.total_size = total
        result.items = merged[:self.top_n]
        result.item_count = len(merged)
        result.scan_time_ms = (time.time() - start) * 1000
        return result
