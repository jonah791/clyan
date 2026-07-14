from abc import ABC, abstractmethod
from typing import Any

from .size import format_size


class ScanResult:
    def __init__(self):
        self.items: list[dict] = []
        self.total_size: int = 0
        self.item_count: int = 0
        self.errors: list[str] = []
        self.scan_time_ms: float = 0.0
        self.extra: dict = {}

    def to_dict(self) -> dict:
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
