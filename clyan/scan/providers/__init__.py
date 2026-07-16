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
    confidence: float = 1.0          # 0.0–1.0, computed by confidence engine
    reason: str = ""                  # human-readable explanation for confidence
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        base = {
            "path": self.path,
            "size": self.size,
            "size_human": format_size(self.size),
            "provider": self.provider,
            "label": self.label,
            "safety": self.safety.value,
            "safety_label": self.safety.label(),
            "confidence": round(self.confidence, 2),
        }
        if self.reason:
            base["reason"] = self.reason
        return {**base, **self.extra}


ProviderFunc = Callable[[str], list[CacheItem]]

_registry: dict[str, ProviderFunc] = {}
_provider_meta: dict[str, dict] = {}


def register(name: str, fn: ProviderFunc):
    """Legacy registration. Prefer @register_provider for new code."""
    _registry[name] = fn
    _provider_meta[name] = {"ecosystem": "other", "safety": "safe", "cost": "unknown"}


def register_provider(
    name: str,
    ecosystem: str = "other",
    default_safety: str = "safe",
    default_cost: str = "unknown",
    needs_protection: bool = True,
):
    """Decorator that registers a provider and auto-configures all layers.

    Layers auto-handled:
      1. Core: registers scan function ✓
      2. Protection: wraps function with is_protected filtering ✓
      3. Classification: sets SafetyLevel from default_safety ✓
      4. Signals: attached by _attach_signals in detect_all ✓
      5. Impact: auto-added to _IMPACT_DB (lazy) ✓
      6. Ecosystem: mapped from 'ecosystem' param ✓
      7. Learning: attached by compute_and_attach pipeline ✓

    Usage:
        @register_provider("my_provider", ecosystem="app", default_cost="low")
        def _scan_my(root):
            ...
            yield CacheItem(path=..., size=..., label="...")
    """
    def decorator(fn: ProviderFunc) -> ProviderFunc:
        # Layer 2: wrap with protection check
        if needs_protection:
            from ...core.config import is_protected
            original_fn = fn
            def protected_fn(root: str) -> list[CacheItem]:
                items = original_fn(root)
                return [i for i in items if not is_protected(i.path)]
            fn = protected_fn

        # Layer 1: register
        _registry[name] = fn
        _provider_meta[name] = {
            "ecosystem": ecosystem,
            "safety": default_safety,
            "cost": default_cost,
        }

        # Layer 5: ensure impact entry exists
        try:
            from ...utils.impact import _IMPACT_DB
            if name not in _IMPACT_DB:
                _IMPACT_DB[name] = (
                    [f"Unknown {ecosystem} cache deleted -- check specific type"],
                    [],
                    default_cost,
                )
        except Exception:
            pass

        return fn
    return decorator


def _attach_signals(items: list[CacheItem]) -> None:
    """Attach age_days and tool_installed signals to CacheItem objects.

    Only computes if the provider hasn't already supplied them.
    """
    from ...utils.staleness import get_age_days, cache_type_installed

    for item in items:
        if "age_days" not in item.extra:
            age = get_age_days(item.path)
            if age is not None:
                item.extra["age_days"] = age
        if "tool_installed" not in item.extra:
            item.extra["tool_installed"] = cache_type_installed(item.provider)


def detect_all(root: str) -> tuple[dict[str, list[CacheItem]], list[str]]:
    """Run all registered providers, return (results, errors)."""
    results: dict[str, list[CacheItem]] = {}
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=min(8, len(_registry) or 1)) as pool:
        futures = {pool.submit(fn, root): name for name, fn in _registry.items()}
        for f in as_completed(futures):
            name = futures[f]
            try:
                items = f.result()
                if items:
                    results[name] = items
                    _attach_signals(items)
            except Exception as e:
                err_msg = f"provider '{name}' failed: {e}"
                errors.append(err_msg)
                results[name] = []
    return results, errors


def get_registered_providers() -> list[str]:
    return list(_registry.keys())


from . import node, python_prov, rust_prov, ide, build, misc, windows_system, app_caches, win_deep, maven, windows_extra, winapp2_prov, npm_deep, pip_deep, windows_installer, dism_cleanup, npm_prune, small_files, vm_caches, windows_logs, empty_dirs, gpu_caches, unknown_caches
