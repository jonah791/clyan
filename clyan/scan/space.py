import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from ..utils.scanner_base import ScanResult, BaseScanner


_SKIP_DIRS = {"$Recycle.Bin", "System Volume Information", "Recovery",
              "Windows.old", "Config.Msi", "$SysReset", "MSOCache"}


def _scan_one(path: str, max_depth: int, current_depth: int) -> tuple:
    results = []
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    name = e.name
                    if e.is_dir(follow_symlinks=False):
                        if name in _SKIP_DIRS and current_depth <= 1:
                            continue
                        sz = _get_dir_size(e.path) if current_depth >= max_depth else 0
                        total += sz
                        entry = {"path": e.path, "size": sz, "is_dir": True}
                        if current_depth < max_depth:
                            sub, sub_sz = _scan_one(e.path, max_depth, current_depth + 1)
                            entry["children"] = sub
                            entry["size"] = sub_sz
                            total += sub_sz
                        results.append(entry)
                    else:
                        s = e.stat().st_size
                        total += s
                        results.append({"path": e.path, "size": s, "is_dir": False})
                except Exception:
                    pass
    except Exception:
        pass
    return results, total


def _get_dir_size(path: str) -> int:
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                    elif e.is_dir(follow_symlinks=False):
                        total += _get_dir_size(e.path)
                except Exception:
                    pass
    except Exception:
        pass
    return total


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

        import multiprocessing
        ncpu = max(1, multiprocessing.cpu_count() - 1)
        if ncpu > 8:
            ncpu = 8
        n_workers = min(ncpu, len(entries))

        all_parts = []
        with ProcessPoolExecutor(max_workers=n_workers) as pool:
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
