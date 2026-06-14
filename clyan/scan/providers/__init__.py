import os
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from ...core.config import DangerLevel as SafetyLevel


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
            "size_human": self._fmt(self.size),
            "provider": self.provider,
            "label": self.label,
            "safety": self.safety.value,
            "safety_label": self.safety.label(),
            **self.extra,
        }

    @staticmethod
    def _fmt(size: int) -> str:
        suffixes = ["B", "KB", "MB", "GB", "TB"]
        idx = 0
        v = float(size)
        while v >= 1024 and idx < len(suffixes) - 1:
            v /= 1024
            idx += 1
        return f"{v:.2f} {suffixes[idx]}"


ProviderFunc = Callable[[str], list[CacheItem]]

_registry: dict[str, ProviderFunc] = {}


def register(name: str, fn: ProviderFunc):
    _registry[name] = fn


def detect_all(root: str) -> dict[str, list[CacheItem]]:
    results = {}
    for name, fn in _registry.items():
        try:
            items = fn(root)
            if items:
                results[name] = items
        except Exception as e:
            results[name] = []
    return results


def get_registered_providers() -> list[str]:
    return list(_registry.keys())


from . import node, python_prov, rust_prov, ide, build, misc, windows_system, app_caches, win_deep
