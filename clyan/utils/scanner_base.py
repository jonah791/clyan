"""Base scanner types and shared utilities."""
from abc import ABC, abstractmethod
from typing import Any

from .size import format_size
from .staleness import get_age_days, cache_type_installed
from .confidence import compute_and_attach
from .impact import attach_impact

# Cache provider feedback to avoid repeated DB queries per item
_feedback_cache: dict[str, dict] = {}


def _get_provider_accuracy(provider: str) -> dict | None:
    if not provider:
        return None
    if provider in _feedback_cache:
        return _feedback_cache[provider]
    try:
        from ..core.history import get_provider_feedback
        data = get_provider_feedback(provider, limit=5)
        if data:
            avg_acc = round(sum(f["accuracy_ratio"] for f in data) / len(data), 2)
            total_pred = sum(f["predicted_size"] for f in data)
            total_act = sum(f["actual_freed"] for f in data)
            result = {
                "clean_count": len(data),
                "avg_accuracy": avg_acc,
                "total_predicted": total_pred,
                "total_actual": total_act,
            }
            _feedback_cache[provider] = result
            return result
    except Exception:
        pass
    _feedback_cache[provider] = None
    return None


def safe_walk(root: str, max_depth: int = 20, skip_permission_errors: bool = True):
    """Generator wrapper around os.walk that tolerates permission errors."""
    import os
    for dirpath, dirs, files in os.walk(root, topdown=True, followlinks=False):
        rel = os.path.relpath(dirpath, root)
        if rel != ".":
            depth = rel.count(os.sep) + 1
            if depth > max_depth:
                dirs.clear()
                continue
        yield dirpath, dirs, files


def _enrich(item: dict) -> None:
    """Attach age_days, tool_installed, impact, and historical accuracy."""
    if "age_days" not in item:
        age = get_age_days(item.get("path", ""))
        item["age_days"] = age if age is not None else -1
    if "tool_installed" not in item:
        item["tool_installed"] = cache_type_installed(item.get("provider", ""))
    attach_impact(item)
    # Historical accuracy from past clean operations (E)
    if "historical_accuracy" not in item:
        fb = _get_provider_accuracy(item.get("provider", ""))
        if fb:
            item["historical_accuracy"] = fb


class ScanResult:
    def __init__(self):
        self.items: list[dict] = []
        self.total_size: int = 0
        self.item_count: int = 0
        self.errors: list[str] = []
        self.scan_time_ms: float = 0.0
        self.extra: dict = {}

    def to_dict(self) -> dict:
        for item in self.items:
            _enrich(item)
            compute_and_attach(item)
        d = {
            "total_size": self.total_size,
            "total_size_human": format_size(self.total_size),
            "item_count": self.item_count,
            "items": self.items,
            "errors": self.errors,
            "scan_time_ms": round(self.scan_time_ms, 1),
        }
        if self.extra:
            d.update(self.extra)
        return d


class BaseScanner(ABC):
    @abstractmethod
    def scan(self) -> ScanResult:
        ...
