import os
import time
from ..utils.scanner_base import ScanResult, BaseScanner
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

        if not os.path.exists(self.root):
            result.errors.append(f"path not found: {self.root}")
            result.scan_time_ms = (time.time() - start) * 1000
            return result

        # Phase 1: Fast unified walk (one os.walk for all directory patterns)
        matched = fast_scan(self.root, max_depth=6)

        # Phase 2: Provider-based system cache detection
        provider_items = providers.detect_all(self.root)

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
        for pname, items in provider_items.items():
            all_items.extend(items)

        # Post-process: override safety for items under protected paths
        for item in all_items:
            if is_protected(item.path):
                item.safety = DangerLevel.UNSAFE

        all_items.sort(key=lambda x: x.size, reverse=True)

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
                "total_size_human": _fmt(total),
                "item_count": len(items),
            })

        result.total_size = sum(i.size for i in all_items)
        result.item_count = len(all_items)
        result.items = [i.to_dict() for i in all_items]
        result.extra = {
            "provider_summaries": provider_summaries,
            "providers_scanned": providers.get_registered_providers(),
        }
        result.scan_time_ms = (time.time() - start) * 1000
        return result


def _fmt(size: int) -> str:
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    v = float(size)
    while v >= 1024 and idx < len(suffixes) - 1:
        v /= 1024
        idx += 1
    return f"{v:.2f} {suffixes[idx]}"
