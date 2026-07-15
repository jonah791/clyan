import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..utils.scanner_base import ScanResult, BaseScanner
from ..utils.dirtree import reset_dir_total_cache
from ..utils.size import format_size
from ..core.config import DangerLevel, is_protected
from . import providers
from .fast_scanner import fast_scan, register_pattern
from .providers import CacheItem


# Register all directory patterns for unified scanning
register_pattern("node_modules", ["node_modules"])
register_pattern("target", ["target"])
register_pattern("python_cache", ["__pycache__", ".venv", "venv", ".env", "env", ".direnv",
                                   ".mypy_cache", ".pytest_cache", ".ruff_cache", ".hypothesis"])
register_pattern("build_artifacts", [".next", "dist", "build", ".turbo", ".cache",
                                      "out", ".output", ".nuxt", ".svelte-kit",
                                      ".expo", "coverage", ".parcel-cache"])
register_pattern("gradle", [".gradle"])
register_pattern("flutter", [".dart_tool", ".fvm"])


def _match_provider(dir_name: str) -> str:
    m = {
        "node_modules": "node_modules",
        "target": "target",
        "__pycache__": "python",
        ".venv": "venv",
        "venv": "venv",
        ".env": "venv",
        "env": "venv",
        ".direnv": "venv",
        ".mypy_cache": "python",
        ".pytest_cache": "python",
        ".ruff_cache": "python",
        ".hypothesis": "python",
        ".next": "build_artifacts",
        "dist": "build_artifacts",
        "build": "build_artifacts",
        ".turbo": "build_artifacts",
        ".cache": "build_artifacts",
        "out": "build_artifacts",
        ".output": "build_artifacts",
        ".nuxt": "build_artifacts",
        ".svelte-kit": "build_artifacts",
        ".expo": "build_artifacts",
        "coverage": "build_artifacts",
        ".parcel-cache": "build_artifacts",
        ".gradle": "gradle",
        ".dart_tool": "flutter",
        ".fvm": "flutter",
    }
    return m.get(dir_name, "unknown")


def _safety_for(dir_name: str) -> DangerLevel:
    return DangerLevel.for_dirname(dir_name)


class DevGarbageScanner(BaseScanner):
    def __init__(self, root: str = None):
        self.root = root or os.environ.get("USERPROFILE", "C:\\")

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()
        reset_dir_total_cache()

        if not os.path.exists(self.root):
            result.errors.append(f"path not found: {self.root}")
            result.scan_time_ms = (time.time() - start) * 1000
            return result

        try:
            # Run pattern walk and provider scans in parallel (both I/O-bound, independent)
            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(fast_scan, self.root, 6)
                f2 = pool.submit(providers.detect_all, self.root)
                provider_results, provider_errors = f2.result()
                matched = f1.result()

            for err in provider_errors:
                result.errors.append(err)

            all_items: list[CacheItem] = []

            # Convert fast scan results
            for key, entries in matched.items():
                for entry in entries:
                    dir_name = entry.get("dir_name", "")
                    all_items.append(CacheItem(
                        path=entry["path"],
                        size=entry["size"],
                        provider=_match_provider(dir_name),
                        label=f"{dir_name} ({entry.get('project', '')})",
                        safety=_safety_for(dir_name),
                        extra={"type": dir_name, "project": entry.get("project", "")},
                    ))

            # Add provider-based results (system-wide caches)
            for pname, items in provider_results.items():
                all_items.extend(items)

            # Post-process: override safety for items under protected paths
            for item in all_items:
                if is_protected(item.path):
                    item.safety = DangerLevel.UNSAFE

            # Dedup by path (keep largest size for duplicates)
            seen: dict[str, CacheItem] = {}
            for item in all_items:
                if item.path not in seen or item.size > seen[item.path].size:
                    seen[item.path] = item
            all_items = sorted(seen.values(), key=lambda x: x.size, reverse=True)

            # Build per-provider summaries
            by_provider: dict[str, list[CacheItem]] = {}
            for item in all_items:
                p = item.provider
                if p not in by_provider:
                    by_provider[p] = []
                by_provider[p].append(item)

            provider_summaries = []
            for pname, items in sorted(by_provider.items(), key=lambda x: -sum(i.size for i in x[1])):
                total = sum(i.size for i in items)
                provider_summaries.append({
                    "provider": pname,
                    "total_size": total,
                    "total_size_human": format_size(total),
                    "item_count": len(items),
                })

            result.total_size = sum(i.size for i in all_items)
            result.item_count = len(all_items)
            result.items = [i.to_dict() for i in all_items]
            result.extra = {
                "provider_summaries": provider_summaries,
                "providers_scanned": providers.get_registered_providers(),
            }
        except Exception as e:
            result.errors.append(f"scan failed: {e}")
        result.scan_time_ms = (time.time() - start) * 1000
        return result



