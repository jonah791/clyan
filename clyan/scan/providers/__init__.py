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
    """Legacy registration. Prefer @register_provider for new code.
    
    Auto-assigns ecosystem + impact from provider name pattern.
    """
    _registry[name] = fn
    # Auto-detect ecosystem from name
    eco = _auto_ecosystem(name)
    _provider_meta[name] = {"ecosystem": eco, "safety": "safe", "cost": "unknown"}
    # Auto-add impact entry if missing
    try:
        from ...utils.impact import _IMPACT_DB
        if name not in _IMPACT_DB:
            _IMPACT_DB[name] = (
                [f"{name} cache cleared — impact varies"],
                [],
                "unknown",
            )
    except Exception:
        pass


def _auto_ecosystem(name: str) -> str:
    """Infer ecosystem from provider name."""
    n = name.lower()
    if any(k in n for k in ["npm", "node", "pnpm", "bun", "yarn"]):
        return "node"
    if any(k in n for k in ["pip", "python", "venv", "uv"]):
        return "python"
    if any(k in n for k in ["cargo", "rust"]):
        return "rust"
    if any(k in n for k in ["go_"]):
        return "go"
    if any(k in n for k in ["gradle", "maven"]):
        return "java"
    if any(k in n for k in ["nuget", "dotnet"]):
        return "dotnet"
    if any(k in n for k in ["browser", "chrome", "edge", "firefox"]):
        return "browser"
    if any(k in n for k in ["vscode", "jetbrains", "ide", "android", "vsstudio"]):
        return "ide"
    if any(k in n for k in ["windows", "winsxs", "system", "win_", "dism",
                              "driver", "prefetch", "thumbnail", "font",
                              "recycle", "wer", "search", "cleanmgr",
                              "delivery", "software_distribution", "store_cache",
                              "defender", "xbox", "old_windows"]):
        return "windows"
    if any(k in n for k in ["discord", "slack", "teams", "zoom", "wechat",
                              "spotify", "whatsapp", "obsidian"]):
        return "app"
    if any(k in n for k in ["ml_", "docker", "huggingface", "ollama"]):
        return "ml"
    if any(k in n for k in ["build", "target"]):
        return "build"
    if any(k in n for k in ["gpu", "shader", "steam"]):
        return "game"
    return "other"


def register_provider(
    name: str,
    ecosystem: str = "other",
    default_safety: str = "safe",
    default_cost: str = "unknown",
    needs_protection: bool = True,
):
    """Register a scan provider with full three-layer pipeline.

    ╔══════════════════════════════════════════════════╗
    ║  三层架构: 扫描层 → 安全层 → 汇报层              ║
    ╠══════════════════════════════════════════════════╣
    ║ Layer 1 扫描层: return (path, size) tuples      ║
    ║   → 纯发现，不做判断                             ║
    ╠══════════════════════════════════════════════════╣
    ║ Layer 2 安全层: @register_provider 自动处理      ║
    ║   → is_protected 过滤                            ║
    ║   → SafetyLevel 分配                             ║
    ║   → Signals: age_days / tool_installed           ║
    ║   → Impact: would_break / recovery_cost          ║
    ║   → Ecosystem 分组                               ║
    ║   → Confidence 评分 + Learning 调整              ║
    ╠══════════════════════════════════════════════════╣
    ║ Layer 3 汇报层: build_report()                   ║
    ║   → 结构化 JSON                                  ║
    ║   → 分阶段执行计划 (Phase 1/2/3/4)              ║
    ║   → 推荐策略                                    ║
    ╚══════════════════════════════════════════════════╝

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
    """Run all registered providers, return (results, errors).
    
    Universal Layer 2 (Safety):
      - All items filtered through is_protected()
      - Signals attached via _attach_signals
    """
    from ...core.config import is_protected
    results: dict[str, list[CacheItem]] = {}
    errors: list[str] = []
    PROVIDER_TIMEOUT = 30  # max seconds per provider
    with ThreadPoolExecutor(max_workers=min(8, len(_registry) or 1)) as pool:
        futures = {pool.submit(fn, root): name for name, fn in _registry.items()}
        for f in as_completed(futures):
            name = futures[f]
            try:
                items = f.result(timeout=PROVIDER_TIMEOUT)
                if items:
                    items = [i for i in items if not is_protected(i.path)]
                    results[name] = items
                    _attach_signals(items)
            except Exception as e:
                err_msg = f"provider '{name}' failed: {e}"
                errors.append(err_msg)
                results[name] = []
    return results, errors


def get_registered_providers() -> list[str]:
    return list(_registry.keys())


def benchmark_providers(root: str, top_n: int = 10) -> list[dict]:
    """Time each provider and return sorted results."""
    import time
    results = []
    for name, fn in _registry.items():
        t0 = time.time()
        try:
            items = fn(root)
            t = time.time() - t0
            size = sum(i.size for i in items) if items else 0
            results.append({"provider": name, "time_s": round(t, 3), "items": len(items or []), "size_mb": round(size/1e6, 1)})
        except Exception as e:
            results.append({"provider": name, "time_s": round(time.time()-t0, 3), "error": str(e)[:50]})
    results.sort(key=lambda x: -x["time_s"])
    return results[:top_n]


from . import node, python_prov, rust_prov, ide, build, misc, windows_system, app_caches, win_deep, maven, windows_extra, winapp2_prov, npm_deep, pip_deep, windows_installer, dism_cleanup, npm_prune, small_files, vm_caches, windows_logs, empty_dirs, gpu_caches, unknown_caches
