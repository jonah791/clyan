import os
import time
import hashlib
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..utils.scanner_base import ScanResult, BaseScanner, safe_walk
from ..utils.size import format_size


_BLOCK_SIZE = 65536
_HASH_THREADS = 4


def _file_hash(path: str, size: int) -> str:
    try:
        h = hashlib.blake2b()
        with open(path, "rb", buffering=0) as f:
            if size <= _BLOCK_SIZE:
                h.update(f.read())
            else:
                h.update(f.read(_BLOCK_SIZE))
                f.seek(max(0, size - _BLOCK_SIZE))
                h.update(f.read(_BLOCK_SIZE))
        return h.hexdigest()[:16]
    except Exception:
        return ""


def _full_hash(path: str) -> str:
    try:
        h = hashlib.blake2b()
        with open(path, "rb", buffering=0) as f:
            while True:
                chunk = f.read(4194304)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _find_duplicates(root: str) -> list[dict]:
    scan_start = time.time()

    by_size: dict[int, list[str]] = defaultdict(list)
    skipped = 0
    total_files = 0

    for dirpath, dirs, files in safe_walk(root, max_depth=8):
        if dirpath.startswith("C:\\Windows") or dirpath.startswith("C:\\Program Files"):
            if dirpath.count(os.sep) > 2:
                dirs.clear()
                continue
        for f in files:
            fp = os.path.join(dirpath, f)
            try:
                st = os.stat(fp)
                if st.st_size < 1024:
                    skipped += 1
                    continue
                by_size[st.st_size].append(fp)
                total_files += 1
            except Exception:
                skipped += 1

    candidates = {sz: paths for sz, paths in by_size.items() if len(paths) > 1}

    scan_time = time.time() - scan_start

    # Phase 2: partial hash
    partial_groups: dict[str, list[str]] = defaultdict(list)
    hash_lock = threading.Lock()

    def _hash_file(fp_size):
        fp, sz = fp_size
        h = _file_hash(fp, sz)
        if h:
            with hash_lock:
                partial_groups[f"{sz}:{h}"].append(fp)

    hash_start = time.time()
    hash_tasks = [(fp, sz) for sz, paths in candidates.items() for fp in paths]
    with ThreadPoolExecutor(max_workers=_HASH_THREADS) as pool:
        list(pool.map(_hash_file, hash_tasks))

    hash_time = time.time() - hash_start

    # Phase 3: full hash for collision groups
    full_dupes = {}
    for key, paths in partial_groups.items():
        if len(paths) < 2:
            continue
        if len(paths) == 2:
            # Two files with same partial hash - compute full hash
            h0 = _full_hash(paths[0])
            h1 = _full_hash(paths[1])
            if h0 == h1:
                full_dupes.setdefault(h0, []).extend(paths)
            continue
        # Multiple files - group by full hash
        by_full = defaultdict(list)
        for p in paths:
            h = _full_hash(p)
            by_full[h].append(p)
        for h, group in by_full.items():
            if len(group) > 1:
                full_dupes.setdefault(h, []).extend(group)

    full_time = time.time() - hash_start

    results = []
    total_savings = 0
    for dupe_hash, paths in full_dupes.items():
        paths.sort(key=lambda p: os.path.getmtime(p))
        keep = paths[0]
        dupes = []
        for p in paths[1:]:
            try:
                sz = os.path.getsize(p)
                dupes.append({"path": p, "size": sz})
                total_savings += sz
            except Exception:
                pass
        if dupes:
            results.append({
                "keep": keep,
                "duplicates": dupes,
                "duplicate_count": len(dupes),
                "savings": sum(d["size"] for d in dupes),
            })

    results.sort(key=lambda x: x["savings"], reverse=True)

    return {
        "scan_time": round(scan_time, 1),
        "hash_time": round(hash_time, 1),
        "full_hash_time": round(full_time - hash_time, 1),
        "total_files_scanned": total_files,
        "size_groups": len(candidates),
        "duplicate_groups": len(results),
        "total_savings": total_savings,
        "duplicates": results,
    }


class DuplicateScanner(BaseScanner):
    def __init__(self, path: str):
        self.path = path

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        if not os.path.exists(self.path):
            result.errors.append(f"path not found: {self.path}")
            result.scan_time_ms = (time.time() - start) * 1000
            return result

        data = _find_duplicates(self.path)

        for group in data["duplicates"]:
            result.items.append({
                "keep": group["keep"],
                "duplicates": group["duplicates"],
                "duplicate_count": group["duplicate_count"],
                "savings": group["savings"],
                "savings_human": format_size(group["savings"]),
            })
            result.total_size += group["savings"]

        result.item_count = data["duplicate_groups"]
        result.extra = {
            "scan_phase_ms": data["scan_time"] * 1000,
            "hash_phase_ms": data["hash_time"] * 1000,
            "total_files_scanned": data["total_files_scanned"],
            "size_groups": data["size_groups"],
        }
        result.scan_time_ms = (time.time() - start) * 1000
        return result



