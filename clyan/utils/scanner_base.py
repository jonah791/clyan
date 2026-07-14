from abc import ABC, abstractmethod
from typing import Any

from .size import format_size
from .staleness import get_age_days, cache_type_installed
from .confidence import compute_and_attach


def _enrich(item: dict) -> None:
    """Attach age_days and tool_installed signals to an item dict."""
    if "age_days" not in item:
        age = get_age_days(item.get("path", ""))
        item["age_days"] = age if age is not None else -1
    if "tool_installed" not in item:
        item["tool_installed"] = cache_type_installed(item.get("provider", ""))


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
