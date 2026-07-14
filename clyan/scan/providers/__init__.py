import os
import time
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional
from ...core.config import DangerLevel as SafetyLevel
from ...utils.size import format_size


@dataclass
class CacheItem:
    path: str
    size: int
    provider: str
    label: str
    safety: SafetyLevel = SafetyLevel.SAFE
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "size_human": format_size(self.size),
            "provider": self.provider,
            "label": self.label,
            "safety": self.safety.value,
            "safety_label": self.safety.label(),
            **self.extra,
        }


ProviderFunc = Callable[[str], list[CacheItem]]

_registry: dict[str, ProviderFunc] = {}


def register(name: str, fn: ProviderFunc):
    _registry[name] = fn


def detect_all(root: str) -> dict[str, list[CacheItem]]:
    results = {}
    # Run independent provider scans in parallel (I/O-bound)
    with ThreadPoolExecutor(max_workers=min(8, len(_registry) or 1)) as pool:
        futures = {pool.submit(fn, root): name for name, fn in _registry.items()}
        for f in as_completed(futures):
            name = futures[f]
            try:
                items = f.result()
                if items:
                    results[name] = items
            except Exception:
                results[name] = []
    return results


def get_registered_providers() -> list[str]:
    return list(_registry.keys())


from . import node, python_prov, rust_prov, ide, build, misc, windows_system, app_caches, win_deep
