"""node_modules internal waste detection — modclean-inspired.

Walks project trees, finds node_modules directories, and identifies
non-essential files that can be safely removed without breaking the
installed package (README, LICENSE, tests, docs, etc.).
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..utils.scanner_base import ScanResult, BaseScanner, safe_walk
from ..utils.dirtree import dir_total
from ..utils.size import format_size
from ..utils.system_drive import system_root_path
from ..utils.system_drive import system_root_path as win_path

# Glob-like name patterns for non-essential files inside node_modules
# Modclean's "safe" mode patterns — safe to delete without breaking code.
_NON_ESSENTIAL_FILES = {
    # Markdown / docs
    "readme.md", "readme.markdown", "readme",
    "changelog.md", "changelog.markdown", "changelog",
    "history.md", "history.markdown",
    "contributing.md", "contributing",
    "code_of_conduct.md", "code_of_conduct",
    "security.md",
    # License
    "license", "license.md", "license.txt",
    "licence", "licence.md", "licence.txt",
    "license-mit", "license-apache", "license-bsd",
    # Meta
    "authors", "contributors", "mailinglist",
    # CI
    ".travis.yml", ".travis.yaml",
    "appveyor.yml", "appveyor.yaml",
    ".circleci", ".github/workflows",
    ".gitlab-ci.yml",
    # Editor
    ".editorconfig", ".jsbeautifyrc",
    ".jshintrc", ".jshintignore",
    ".eslintrc", ".eslintignore",
    ".jscsrc", ".jscs.json",
    ".npmignore", ".gitkeep",
    # Linters / formatters
    ".prettierrc", ".prettierignore",
    ".stylelintrc", ".stylelintignore",
    ".huskyrc",
}

_NON_ESSENTIAL_DIRS = {
    "test", "tests", "testing",
    "spec", "specs",
    "demo", "demos",
    "example", "examples",
    "sample", "samples",
    "doc", "docs", "documentation",
    "coverage", ".nyc_output",
    ".github", ".git",
    "benchmark", "benchmarks",
    "perf", "performance",
}

# Extensions that are safe to remove when paired with a .js counterpart
_REDUNDANT_EXTENSIONS = {".flow", ".ts", ".map", ".d.ts"}


def _scan_node_modules(nm_path: str) -> list[dict]:
    """Scan a single node_modules directory for waste files.
    Returns list of {path, size} dicts."""
    results = []
    try:
        for dirpath, dirs, files in safe_walk(nm_path, max_depth=6):
            # Skip nested node_modules
            basename = os.path.basename(dirpath)
            if basename == "node_modules" and dirpath != nm_path:
                dirs.clear()
                continue
            # Skip .bin (symlinks to executables)
            if basename == ".bin":
                dirs.clear()
                continue
            # Check dirs
            for d in list(dirs):
                if d.lower() in _NON_ESSENTIAL_DIRS:
                    fp = os.path.join(dirpath, d)
                    sz = dir_total(fp, max_depth=1)
                    if sz > 0:
                        results.append({
                            "path": fp, "size": sz,
                            "type": "dir", "pattern": d,
                        })
                    dirs.remove(d)
            # Check files
            for f in files:
                f_lower = f.lower()
                if f_lower in _NON_ESSENTIAL_FILES:
                    fp = os.path.join(dirpath, f)
                    try:
                        sz = os.path.getsize(fp)
                        if sz > 0:
                            results.append({
                                "path": fp, "size": sz,
                                "type": "file", "pattern": f_lower,
                            })
                    except Exception:
                        pass
                else:
                    # Check redundant extensions (e.g., .flow alongside .js)
                    for ext in _REDUNDANT_EXTENSIONS:
                        if f_lower.endswith(ext):
                            base_no_ext = f_lower[:-len(ext)]
                            js_path = os.path.join(dirpath, base_no_ext + ".js")
                            if os.path.isfile(js_path):
                                fp = os.path.join(dirpath, f)
                                try:
                                    sz = os.path.getsize(fp)
                                    if sz > 0:
                                        results.append({
                                            "path": fp, "size": sz,
                                            "type": "redundant_ext",
                                            "pattern": ext,
                                        })
                                except Exception:
                                    pass
                            break
    except Exception:
        pass
    return results


def _find_node_waste(root: str) -> list[dict]:
    """Find all node_modules directories under root and scan each for waste."""
    nm_dirs = []
    for dirpath, dirs, files in safe_walk(root, max_depth=8):
        if os.path.basename(dirpath) == "node_modules":
            nm_dirs.append(dirpath)
            dirs.clear()  # Don't recurse into
        elif any(dirpath.startswith(p) for p in (
            win_path("Windows"), win_path("Program Files"), win_path("Program Files (x86)"),
            win_path("ProgramData"),
        )):
            dirs.clear()

    all_waste = []
    with ThreadPoolExecutor(max_workers=min(8, len(nm_dirs))) as pool:
        futures = {pool.submit(_scan_node_modules, d): d for d in nm_dirs}
        for f in as_completed(futures):
            try:
                all_waste.extend(f.result())
            except Exception:
                pass

    # Aggregate by content type
    by_pattern: dict[str, int] = {}
    by_type: dict[str, int] = {}
    total_size = 0
    for w in all_waste:
        total_size += w["size"]
        pt = w["pattern"]
        by_pattern[pt] = by_pattern.get(pt, 0) + w["size"]
        tp = w["type"]
        by_type[tp] = by_type.get(tp, 0) + w["size"]

    return {
        "total_size": total_size,
        "items": all_waste,
        "pattern_summary": sorted(
            [{"pattern": k, "size": v} for k, v in by_pattern.items()],
            key=lambda x: -x["size"],
        ),
        "type_summary": sorted(
            [{"type": k, "size": v} for k, v in by_type.items()],
            key=lambda x: -x["size"],
        ),
    }


class NodeWasteScanner(BaseScanner):
    """Scanner for non-essential files inside node_modules."""

    def __init__(self, path: str = None):
        self.path = path or os.environ.get("USERPROFILE", "C:\\")

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        if not os.path.exists(self.path):
            result.errors.append(f"path not found: {self.path}")
            result.scan_time_ms = (time.time() - start) * 1000
            return result

        data = _find_node_waste(self.path)

        for item in data["items"]:
            lbl = f"node_waste/{item['type']}: {item['pattern']}"
            result.items.append({
                "path": item["path"],
                "size": item["size"],
                "size_human": format_size(item["size"]),
                "provider": "node_waste",
                "safety": "safe",
                "label": lbl,
                "extra": {
                    "pattern": item["pattern"],
                    "waste_type": item["type"],
                    "rebuild_cost": "none",
                    "note": "Non-essential file inside node_modules — safe to delete, auto-reinstalled",
                },
            })
            result.total_size += item["size"]

        result.item_count = len(data["items"])
        result.extra = {
            "pattern_summary": data["pattern_summary"],
            "type_summary": data["type_summary"],
            "total_node_modules_scanned": len(data.get("items", [])) or 0,
        }
        result.scan_time_ms = (time.time() - start) * 1000
        return result
