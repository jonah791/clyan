import os
from collections import defaultdict

_SIZE_CACHE: dict[str, int] = {}

_DIR_PATTERNS: dict[str, set[str]] = {}


def register_pattern(key: str, dir_names: list[str]) -> None:
    _DIR_PATTERNS[key] = set(dir_names)


def get_patterns() -> dict[str, set[str]]:
    return dict(_DIR_PATTERNS)


def fast_scan(root: str, max_depth: int = 6) -> dict[str, list[dict]]:
    _SIZE_CACHE.clear()
    root_norm = os.path.normpath(root).lower()
    skip_prefixes = ("c:\\windows", "c:\\program files", "c:\\programdata",
                     "c:\\$recycle.bin", "c:\\recovery", "c:\\system volume information")

    if any(root_norm.startswith(p) for p in skip_prefixes):
        return {}

    patterns = get_patterns()
    if not patterns:
        return {}

    # Build a reverse lookup: dir_name -> list of pattern keys
    name_to_keys: dict[str, list[str]] = {}
    for key, names in patterns.items():
        for n in names:
            if n not in name_to_keys:
                name_to_keys[n] = []
            name_to_keys[n].append(key)

    all_results: dict[str, list[dict]] = defaultdict(list)
    dir_sizes: dict[str, int] = {}       # path -> accumulated size
    matched_dirs: list[tuple[str, str, str, list[str]]] = []  # (full, dir_name, project, keys)

    for dirpath, dirs, files in os.walk(root, topdown=True, followlinks=False):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= max_depth:
            dirs.clear()
            continue

        # Sum sizes of files directly in this directory
        file_size = 0
        for f in files:
            try:
                fp = os.path.join(dirpath, f)
                file_size += os.path.getsize(fp)
            except Exception:
                pass

        # Initialize this dir's size (will accumulate children later)
        dir_sizes[dirpath] = file_size

        # Check each child directory for pattern matches
        for d in list(dirs):
            keys = name_to_keys.get(d)
            if not keys:
                continue
            full = os.path.join(dirpath, d)
            matched_dirs.append((full, d, os.path.basename(dirpath), keys))

        # Prune at max_depth-1 to avoid walking too deep
        if depth >= max_depth - 1:
            dirs.clear()

    # Propagate child sizes up to parents (walk deepest paths first)
    for path in sorted(dir_sizes.keys(), key=len, reverse=True):
        sz = dir_sizes[path]
        parent = os.path.dirname(path)
        if parent in dir_sizes:
            dir_sizes[parent] += sz

    # Fill results from accumulated sizes
    for full, dir_name, project, keys in matched_dirs:
        size = dir_sizes.get(full, 0)
        if size == 0:
            continue
        for key in keys:
            all_results[key].append({
                "path": full,
                "size": size,
                "dir_name": dir_name,
                "project": project,
            })

    return dict(all_results)
