"""Impact prediction for cache cleanup items.

Maps provider types and paths to human-readable impact descriptions.
This is the AI's key decision support — "what happens if I delete this?"

Design: no hard thresholds, no filtering. Just attach structured signals
and let the AI decide.
"""

from __future__ import annotations
import os

# ── Impact knowledge base ──────────────────────────────────────────
# Each provider → (would_break messages, would_affect tools, recovery_cost)
# would_break: what breaks or side effects of deletion
# would_affect: which applications/tools are impacted
# recovery_cost: how hard to recover (none < low < medium < high)

_IMPACT_DB: dict[str, tuple[list[str], list[str], str]] = {
    # === Package manager caches ===
    "npm_cache": (
        ["npm install / ci would re-download all cached packages"],
        ["npm", "node", "npx"],
        "high",
    ),
    "pnpm_cache": (
        ["pnpm install would re-download all cached packages"],
        ["pnpm", "node"],
        "high",
    ),
    "bun_cache": (
        ["bun install would re-download all cached packages"],
        ["bun", "node"],
        "high",
    ),
    "pip_cache": (
        ["pip install would re-download all packages from PyPI"],
        ["pip", "python", "virtualenv"],
        "high",
    ),
    "cargo_registry": (
        ["cargo build would re-download all crate dependencies"],
        ["cargo", "rustc"],
        "high",
    ),
    "go_cache": (
        ["go build would re-download module cache"],
        ["go"],
        "high",
    ),
    "nuget_cache": (
        ["dotnet restore would re-download NuGet packages"],
        ["dotnet"],
        "high",
    ),
    "gradle_cache": (
        ["gradle build would re-download dependencies"],
        ["gradle", "java"],
        "high",
    ),
    "maven_cache": (
        ["mvn build would re-download dependencies"],
        ["mvn", "java"],
        "high",
    ),
    "docker_images": (
        ["Docker containers would need to be re-pulled"],
        ["docker"],
        "high",
    ),
    
    # === Browser caches ===
    "browser": (
        ["Browser may clear login sessions and site preferences"],
        ["chrome", "edge", "firefox"],
        "low",
    ),
    "browser_cache_chrome": (
        ["Chrome may clear login sessions, site data, and cache"],
        ["chrome"],
        "low",
    ),
    "browser_cache_edge": (
        ["Edge may clear login sessions, site data, and cache"],
        ["edge"],
        "low",
    ),
    "browser_cache_firefox": (
        ["Firefox may clear login sessions, site data, and cache"],
        ["firefox"],
        "low",
    ),
    "browser_deep": (
        ["Browser history would be cleared, bookmarks preserved"],
        ["chrome", "edge", "firefox"],
        "none",
    ),

    # === IDE / dev tool caches ===
    "ide": (
        ["IDE cache cleared -- auto-rebuilds on next launch"],
        [],
        "low",
    ),
    "ide:vscode_cache": (
        ["VS Code extension cache may need to re-sync"],
        ["code"],
        "low",
    ),
    "ide:vscode_extensions": (
        ["VS Code extensions would need to be re-downloaded"],
        ["code"],
        "medium",
    ),
    "ide:jetbrains_cache": (
        ["JetBrains IDE caches and indexes would be rebuilt"],
        ["intellij", "pycharm", "webstorm"],
        "medium",
    ),
    "vscode_cache": (
        ["VS Code extension cache may need to re-sync"],
        ["code"],
        "low",
    ),
    "vscode_extensions": (
        ["VS Code extensions would need to be re-downloaded"],
        ["code"],
        "medium",
    ),
    "jetbrains_cache": (
        ["JetBrains IDE caches and indexes would be rebuilt"],
        ["intellij", "pycharm", "webstorm"],
        "medium",
    ),
    "jetbrains_tmp": (
        ["JetBrains temporary files would be cleared, no side effects"],
        ["intellij", "pycharm", "webstorm"],
        "none",
    ),

    # === Build artifacts ===
    "build_artifacts": (
        ["Build output would be deleted, rebuild required"],
        [],
        "medium",
    ),
    "build_artifacts_file": (
        ["Incremental build cache (tsbuildinfo) would be cleared"],
        ["typescript"],
        "low",
    ),
    "node_modules": (
        ["Project dependencies would be deleted, npm/pnpm/yarn install required"],
        ["node", "npm", "pnpm", "yarn"],
        "high",
    ),
    "target": (
        ["Rust build artifacts deleted, cargo build required"],
        ["cargo", "rustc"],
        "high",
    ),

    # === Python ===
    "python:pip_cache": (
        ["pip install would re-download all packages from PyPI"],
        ["pip", "python", "virtualenv"],
        "high",
    ),
    "python": (
        ["Python caches (__pycache__, mypy, pytest) cleared — auto-rebuilt on next run"],
        ["python"],
        "none",
    ),
    "venv": (
        ["Virtual environment deleted, would need recreation and reinstall"],
        ["python", "pip"],
        "high",
    ),

    # === App caches ===
    "app_cache": (
        ["Application cache cleared — may clear login state, auto-rebuilds"],
        [],
        "low",
    ),

    # === Windows system ===
    "win_deep": (
        ["Windows system cache analyzed via DISM -- safe to reclaim space"],
        ["windows"],
        "none",
    ),
    "driver_store": (
        ["Driver store cache -- old driver versions can be removed via DISM"],
        ["windows"],
        "none",
    ),
    "system": (
        ["Temporary files deleted -- no side effects"],
        [],
        "none",
    ),
    "system_temp": (
        ["Temporary files deleted — no side effects, auto-cleaned by Windows"],
        [],
        "none",
    ),
    "windows_update": (
        ["Windows Update cache cleared — updates can re-download if needed"],
        ["windows update"],
        "low",
    ),
    "winsxs": (
        ["WinSxS component store cleanup via DISM — safe, no impact on current system"],
        ["windows"],
        "none",
    ),
    "delivery_optimization": (
        ["Delivery Optimization P2P cache cleared — auto-rebuilds"],
        ["windows update"],
        "none",
    ),
    "software_distribution": (
        ["Windows Update download cache cleared — safe to delete, re-downloaded if needed"],
        ["windows update"],
        "low",
    ),
    "recycle_bin": (
        ["Files in Recycle Bin permanently deleted — cannot be restored"],
        ["windows explorer"],
        "none",
    ),
    "prefetch": (
        ["Windows Prefetch files cleared — slight boot time impact, auto-rebuilds"],
        ["windows"],
        "none",
    ),
    "thumbnail_cache": (
        ["Windows thumbnail cache cleared — auto-rebuilds on folder open"],
        ["windows explorer"],
        "none",
    ),
    "old_windows": (
        ["Previous Windows installation files deleted — cannot roll back Windows version"],
        ["windows recovery"],
        "none",
    ),
    "defender_cache": (
        ["Windows Defender scan history and quarantine deleted"],
        ["windows defender"],
        "none",
    ),
    "wer_reports": (
        ["Windows Error Reporting reports deleted — no impact"],
        [],
        "none",
    ),
    "search_index": (
        ["Windows Search index cleared — will be rebuilt, slower search temporarily"],
        ["windows search"],
        "none",
    ),
    "dotnet_ngen": (
        [".NET Native Images cache cleared — auto-rebuilt by .NET runtime"],
        ["dotnet"],
        "none",
    ),

    # === npm deep ===
    "npm_deep:npx_cache": (
        ["npx downloaded binaries deleted — safe, one-time use only"],
        ["npx", "node"],
        "none",
    ),
    "npm_deep:cacache": (
        ["npm package cache cleared — re-download required on npm install"],
        ["npm", "node"],
        "high",
    ),
    "npm_deep:npm_global": (
        ["npm global packages deleted — npm install -g <pkg> required"],
        ["npm", "node"],
        "high",
    ),

    # === pip deep ===
    "pip_deep:pip_cache": (
        ["pip wheel cache cleared — re-download required on pip install"],
        ["pip", "python"],
        "high",
    ),

    # === ML / AI ===
    "ml_cache": (
        ["ML model cache cleared — large re-download required (GBs)"],
        ["huggingface", "ollama", "pytorch"],
        "high",
    ),

    # === node_waste ===
    "node_waste": (
        ["Non-essential files inside node_modules — safe to delete, npm install restores them"],
        ["node", "npm"],
        "none",
    ),
    "ide:rust": (
        ["Rust build artifacts deleted, cargo build required"],
        ["cargo", "rustc"],
        "high",
    ),
    "windows_extra:old_windows": (
        ["Previous Windows installation files deleted -- cannot roll back"],
        ["windows recovery"],
        "none",
    ),
    "windows_extra:ml_cache": (
        ["ML model cache cleared -- large re-download required (GBs)"],
        ["huggingface", "ollama", "pytorch"],
        "high",
    ),
    "windows_extra:onedrive_cache": (
        ["OneDrive cache cleared -- will be re-downloaded on sync"],
        ["onedrive"],
        "low",
    ),
    "windows_extra:software_distribution": (
        ["Windows Update download cache cleared -- safe"],
        ["windows update"],
        "low",
    ),
    "windows_system": (
        ["Windows system cache -- auto-rebuilds"],
        ["windows"],
        "none",
    ),
    "small_files": (
        ["Small waste files deleted — no impact (desktop.ini, .log, .bak, .dmp)"],
        [],
        "none",
    ),

    "flutter": (
        ["Flutter build cache cleared -- 'flutter pub get' may be needed"],
        ["flutter", "dart"],
        "medium",
    ),

    # === Windows Installer ===
    "windows_installer:old_msp_patches": (
        ["Old Windows update patches deleted — cannot uninstall those specific updates"],
        ["windows installer"],
        "low",
    ),
    "windows_installer:old_msi_files": (
        ["Old MSI installers deleted — affected programs may not uninstall properly"],
        ["windows installer"],
        "low",
    ),

    # === DISM Cleanup ===
    "dism_cleanup:dism_component_cleanup": (
        ["WinSxS component store cleaned — safe, ~30%% space reduction"],
        ["windows"],
        "none",
    ),
    "dism_cleanup:dism_reset_base": (
        ["WinSxS reset base — cannot uninstall current cumulative updates"],
        ["windows"],
        "none",
    ),
    "dism_cleanup:dism_driver_cleanup": (
        ["Old driver versions removed — safe, only outdated drivers"],
        ["windows"],
        "none",
    ),
    "dism_cleanup:dism_delivery_opt": (
        ["Delivery Optimization cache cleared — safe, auto-rebuilds"],
        ["windows update"],
        "none",
    ),

    # === npm prune ===
    "npm_prune:npm_old_versions": (
        ["npm old package versions removed — safe, npm install re-downloads if needed"],
        ["npm", "node"],
        "low",
    ),
    "npm_prune:npm_cache_overview": (
        ["npm cache cleared — all packages re-downloaded on next install"],
        ["npm", "node"],
        "high",
    ),
}


def impact_for(provider: str, path: str = "", extra: dict | None = None) -> dict:
    """Return impact prediction for a cache item.
    
    Returns: {
        "would_break": [str, ...],    # human-readable consequences
        "would_affect": [str, ...],   # affected applications/tools
        "recovery_cost": str,         # none / low / medium / high
    }
    """
    p = (provider or "").lower()
    e = extra or {}

    # Type-based lookup first (e.g., "python:pip_cache" beats "python")
    ctype = e.get("type", "")
    if ctype:
        type_lookup = f"{p}:{ctype}"
        if type_lookup in _IMPACT_DB:
            breaks, affects, cost = _IMPACT_DB[type_lookup]
            return {
                "would_break": breaks,
                "would_affect": affects,
                "recovery_cost": cost,
            }

    # Direct provider lookup
    if p in _IMPACT_DB:
        breaks, affects, cost = _IMPACT_DB[p]
        return {
            "would_break": breaks,
            "would_affect": affects,
            "recovery_cost": cost,
        }

    # Fallback: path heuristics
    if path:
        pl = path.lower().replace("\\", "/")
        if "/node_modules/" in pl:
            return {
                "would_break": ["Project dependencies affected"],
                "would_affect": ["node", "npm"],
                "recovery_cost": "high",
            }
        if pl.endswith("__pycache__") or "/__pycache__/" in pl:
            return {
                "would_break": ["Python bytecode cache — auto-rebuilt"],
                "would_affect": ["python"],
                "recovery_cost": "none",
            }
        if "/temp/" in pl or "/tmp/" in pl:
            return {
                "would_break": [],
                "would_affect": [],
                "recovery_cost": "none",
            }

    # Type-based from extra
    ctype = e.get("type", "")
    if ctype:
        lookup = f"{p}:{ctype}"
        if lookup in _IMPACT_DB:
            breaks, affects, cost = _IMPACT_DB[lookup]
            return {
                "would_break": breaks,
                "would_affect": affects,
                "recovery_cost": cost,
            }

    # Default: unknown — conservative
    return {
        "would_break": [f"Unknown impact for {provider}"],
        "would_affect": [],
        "recovery_cost": "unknown",
    }


def ecosystem_for(provider: str, path: str = "") -> str:
    """Return the ecosystem group for a cache item.
    
    Groups: "node", "python", "rust", "go", "java", "dotnet",
            "browser", "ide", "windows", "ml", "build", "app", "other"
    """
    p = (provider or "").lower()
    
    # Provider-based mapping
    _ECOSYSTEM_MAP = {
        "node": {"npm_cache", "pnpm_cache", "bun_cache", "node_modules", "npm_prune",
                 "node_waste", "build_artifacts", "npm_deep"},
        "python": {"pip_cache", "python", "venv", "uv_cache", "pip_deep"},
        "rust": {"cargo_registry", "target", "rust"},
        "go": {"go_cache"},
        "java": {"gradle_cache", "maven_cache", "gradle"},
        "dotnet": {"nuget_cache"},
        "browser": {"browser_cache", "browser_deep", "app_cache", "browser"},
        "ide": {"vscode_cache", "vscode_extensions", "jetbrains_cache",
                 "jetbrains_tmp", "ide"},
        "windows": {"windows_installer", "dism_cleanup", "system_temp", "windows_update", "winsxs",
                     "delivery_optimization", "software_distribution",
                     "recycle_bin", "prefetch", "thumbnail_cache",
                     "old_windows", "defender_cache", "wer_reports",
                     "search_index", "dotnet_ngen", "windows_extra",
                     "windows_system", "system", "win_deep", "driver_store"},
        "ml": {"ml_cache", "docker_images"},
        "build": {"build_artifacts", "build_artifacts_file"},
        "other": {"small_files"},
        "windows": {"...windows already has full set..."},
    }
    
    for ecosystem, providers in _ECOSYSTEM_MAP.items():
        if p in providers:
            return ecosystem
    
    # Path-based heuristics
    if path:
        pl = path.lower().replace("\\", "/")
        if "/node_modules/" in pl:
            return "node"
        if "/site-packages/" in pl or "/python" in pl:
            return "python"
        if "/target/" in pl:
            return "rust"
    
    return "other"


def attach_impact(item: dict) -> None:
    """Attach impact fields and ecosystem group to an item dict in-place."""
    if "would_break" in item and "recovery_cost" in item and "ecosystem" in item:
        return
    prov = item.get("provider", "")
    path = item.get("path", "")
    # extra may be merged into top-level by CacheItem.to_dict()
    extra = item.get("extra", {}) or {}
    # Check top-level for type-like keys (from CacheItem extra merge)
    if not extra.get("type") and item.get("type"):
        extra = dict(extra)
        extra["type"] = item["type"]
    impact = impact_for(prov, path, extra)
    item.setdefault("would_break", impact["would_break"])
    item.setdefault("would_affect", impact["would_affect"])
    item.setdefault("recovery_cost", impact["recovery_cost"])
    item.setdefault("ecosystem", ecosystem_for(prov, path))
