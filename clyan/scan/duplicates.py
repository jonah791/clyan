import os
import time
import hashlib
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..utils.scanner_base import ScanResult, BaseScanner, safe_walk
from ..utils.size import format_size


# ── P0 improvement 1: 4KB partial hash (one disk block) ──
_BLOCK_SIZE = 4096  # one disk block; was 65536 (128KB)
_HASH_THREADS = 8   # more threads for parallel hash

# Directories to skip in os.walk (clear dirs to avoid recursing into them)
# These are known large artifact/cache dirs unlikely to contain cross-file duplicates.
_SKIP_WALK_DIRS = {
    "node_modules", ".git", ".svn", ".hg", "__pycache__",
    ".cache", ".npm", ".cargo", "bower_components",
    "WinSxS", "System32", "assembly",
}


def _file_hash(path: str, size: int) -> str:
    """P0: 4KB partial hash with 64-bit digest.

    Reads only the first 4KB (one disk block) — ddh's research shows
    4KB provides excellent discrimination vs full read.
    Returns 16-char hex string.
    """
    try:
        h = hashlib.blake2b(digest_size=8)  # 64-bit digest
        with open(path, "rb", buffering=0) as f:
            h.update(f.read(_BLOCK_SIZE))
        return h.hexdigest()
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


def _walk_and_group(root: str, skip_roots: set) -> dict[int, list[str]]:
    """Walk a single directory subtree and return {size: [paths]}.
    Used as a parallel worker in _find_duplicates."""
    by_size: dict[int, list[str]] = defaultdict(list)
    seen_inodes: set[tuple[int, int]] = set()
    try:
        for dirpath, dirs, files in safe_walk(root, max_depth=8):
            # Skip known system roots past depth 2
            if any(dirpath.startswith(r) for r in skip_roots):
                if dirpath.count(os.sep) > 2:
                    dirs.clear()
                    continue
            # P0: match-and-stop — skip known artifact dirs
            for d in list(dirs):
                if d in _SKIP_WALK_DIRS:
                    dirs.remove(d)
            for f in files:
                fp = os.path.join(dirpath, f)
                try:
                    st = os.stat(fp)
                    if st.st_size < 1024:
                        continue
                    # P0 improvement 3: inode dedup
                    inode_key = (st.st_dev, st.st_ino)
                    if inode_key in seen_inodes:
                        continue
                    seen_inodes.add(inode_key)
                    by_size[st.st_size].append(fp)
                except Exception:
                    pass
    except Exception:
        pass
    return dict(by_size)


def _find_duplicates(root: str) -> list[dict]:
    scan_start = time.time()
    total_files = 0
    skipped = 0

    skip_roots = {
        "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
        "C:\\ProgramData", "C:\\Recovery", "C:\\Boot",
    }

    # P0 improvement 2: parallel directory traversal
    # Split root into top-level subdirectories for parallel workers
    top_entries = []
    try:
        for e in os.scandir(root):
            if e.is_dir(follow_symlinks=False):
                name_lower = e.name.lower()
                # Skip known system / temp roots at top level
                if name_lower in ("$recycle.bin", "system volume information",
                                   "recovery", "config.msi", "$sysreset",
                                   "msocache", "boot", "documents and settings",
                                   "temp", "tmp", "windows.old"):
                    skipped += 1
                    continue
                top_entries.append(e.path)
    except Exception:
        # Fallback: walk the root directly
        top_entries = [root]

    if not top_entries:
        top_entries = [root]

    all_by_size: dict[int, list[str]] = defaultdict(list)
    n_workers = min(8, len(top_entries))

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = [pool.submit(_walk_and_group, d, skip_roots) for d in top_entries]
        for f in as_completed(futures):
            try:
                for sz, paths in f.result().items():
                    all_by_size[sz].extend(paths)
            except Exception:
                pass

    total_files = sum(len(paths) for paths in all_by_size.values())
    candidates = {sz: paths for sz, paths in all_by_size.items() if len(paths) > 1}
    scan_time = time.time() - scan_start

    # Phase 2: partial hash (4KB each)
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
            h0 = _full_hash(paths[0])
            h1 = _full_hash(paths[1])
            if h0 == h1:
                full_dupes.setdefault(h0, []).extend(paths)
            continue
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
