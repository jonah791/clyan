"""Scanner for finding the largest individual files on a path.

Useful for answering "what are the biggest files eating my disk space?"
"""
import os
import time
from ..utils.scanner_base import ScanResult, BaseScanner, safe_walk
from ..utils.size import format_size
from ..utils.dirtree import dir_total


class LargeFileScanner(BaseScanner):
    """Find the largest files under *path*.

    Uses ``os.scandir`` for fast traversal.  Skips system-protected roots.
    """

    def __init__(self, path: str, min_size_mb: int = 50, top_n: int = 50):
        self.path = path
        self.min_size = min_size_mb * 1024 * 1024
        self.top_n = top_n

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        if not os.path.exists(self.path):
            result.errors.append(f"path not found: {self.path}")
            result.scan_time_ms = (time.time() - start) * 1000
            return result

        # System roots to skip for deep scanning
        _skip_roots = {
            "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
            "C:\\ProgramData", "C:\\$Recycle.Bin", "C:\\System Volume Information",
            "C:\\Recovery", "C:\\Boot",
        }

        large_files: list[tuple[str, int]] = []

        for dirpath, dirs, files in safe_walk(self.path, max_depth=20):
            dirpath_norm = os.path.normpath(dirpath)
            if any(dirpath_norm.startswith(r) for r in _skip_roots):
                if dirpath.count(os.sep) > 2:
                    dirs.clear()
                    continue

            # Limit depth to 20 levels
            depth = dirpath_norm[len(os.path.normpath(self.path)):].count(os.sep)
            if depth > 20:
                dirs.clear()
                continue

            for f in files:
                fp = os.path.join(dirpath, f)
                try:
                    st = os.stat(fp)
                    if st.st_size >= self.min_size:
                        large_files.append((fp, st.st_size))
                except Exception:
                    pass

            # Early exit if we already have enough candidates sorted
            # (optimization: only matters for very large scans)

        large_files.sort(key=lambda x: -x[1])
        large_files = large_files[:self.top_n]

        for filepath, sz in large_files:
            item = {
                "path": filepath,
                "size": sz,
                "size_human": format_size(sz),
                "type": "file",
                "provider": "large_files",
                "safety": "safe",
                "label": f"Large file: {os.path.basename(filepath)}",
            }
            result.items.append(item)
            result.total_size += sz

        result.item_count = len(result.items)
        result.scan_time_ms = (time.time() - start) * 1000
        return result
