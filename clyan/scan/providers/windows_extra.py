"""Additional Windows system providers — Delivery Optimization, SoftwareDistribution,
Windows Store cache, Teams/OneDrive/Xbox caches, Defender scan history.

These are items an AI agent may choose to clean. No hard-coded thresholds --
just scan, signal, and let the AI decide.
"""

import os
import glob
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total


def _scan_delivery_opt(root: str) -> list[CacheItem]:
    """Windows Delivery Optimization cache (P2P update peer cache).
    Path: ServiceProfiles\\NetworkService\\AppData\\...\\DeliveryOptimization\\Cache
    """
    results = []
    base = (
        os.environ.get("WINDIR", "C:\\Windows")
        + "\\ServiceProfiles\\NetworkService\\AppData\\Local\\Microsoft\\Windows\\DeliveryOptimization\\Cache"
    )
    if os.path.isdir(base):
        sz = dir_total(base)
        if sz > 0:
            results.append(CacheItem(
                path=base, size=sz, provider="windows_extra",
                label="Delivery Optimization Cache (P2P update)",
                safety=SafetyLevel.SAFE,
                extra={"type": "delivery_optimization", "rebuild_cost": "none",
                       "note": "Windows Update P2P cache, auto-rebuilds"},
            ))
    return results


def _scan_software_distribution(root: str) -> list[CacheItem]:
    """Windows Update download cache under SoftwareDistribution\\Download."""
    results = []
    sd = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "SoftwareDistribution", "Download")
    if os.path.isdir(sd):
        sz = dir_total(sd)
        if sz > 0:
            results.append(CacheItem(
                path=sd, size=sz, provider="windows_extra",
                label="Windows Update Download Cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "software_distribution", "rebuild_cost": "low",
                       "note": "Installed update files -- safe to delete"},
            ))
    return results


def _scan_store_cache(root: str) -> list[CacheItem]:
    """Windows Store app cache in ProgramData/LocalAppData."""
    results = []
    for base_var in ("ProgramData", "LOCALAPPDATA"):
        base = os.path.join(os.environ.get(base_var, ""), "Microsoft", "Windows", "Store", "Cache")
        if os.path.isdir(base):
            sz = dir_total(base)
            if sz > 0:
                results.append(CacheItem(
                    path=base, size=sz, provider="windows_extra",
                    label="Windows Store Cache",
                    safety=SafetyLevel.SAFE,
                    extra={"type": "store_cache", "rebuild_cost": "low"},
                ))
    return results


def _scan_teams_cache(root: str) -> list[CacheItem]:
    """Microsoft Teams (classic) cache under AppData."""
    results = []
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Teams")
    if os.path.isdir(base):
        cache_dirs = [
            os.path.join(base, "Cache"),
            os.path.join(base, "Code Cache"),
            os.path.join(base, "Service Worker", "CacheStorage"),
            os.path.join(base, "BrowserCache"),
            os.path.join(base, "databases"),
        ]
        sz = 0
        for cd in cache_dirs:
            if os.path.isdir(cd):
                sz += dir_total(cd)
        if sz > 0:
            results.append(CacheItem(
                path=base, size=sz, provider="windows_extra",
                label="Microsoft Teams Cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "teams_cache", "rebuild_cost": "low",
                       "note": "Teams downloads/browser cache, auto-rebuilds"},
            ))
    return results


def _scan_onedrive_cache(root: str) -> list[CacheItem]:
    """OneDrive sync cache and setup files under LocalAppData."""
    results = []
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "OneDrive")
    if os.path.isdir(base):
        cache_dirs = [
            os.path.join(base, "cache"),
            os.path.join(base, "settings", "cache"),
            os.path.join(base, "logs"),
            os.path.join(base, "Setup", "Downloads"),
        ]
        sz = 0
        for cd in cache_dirs:
            if os.path.isdir(cd):
                sz += dir_total(cd)
        if sz > 0:
            results.append(CacheItem(
                path=base, size=sz, provider="windows_extra",
                label="OneDrive Cache and Logs",
                safety=SafetyLevel.SAFE,
                extra={"type": "onedrive_cache", "rebuild_cost": "low",
                       "note": "Sync cache and installer files"},
            ))
    return results


def _scan_defender_scan_cache(root: str) -> list[CacheItem]:
    """Windows Defender scan history and quarantine under ProgramData."""
    results = []
    base = os.path.join(os.environ.get("ProgramData", "C:\\ProgramData"),
                        "Microsoft", "Windows Defender")
    if os.path.isdir(base):
        scan_dirs = [
            os.path.join(base, "Scans", "History"),
            os.path.join(base, "Quarantine"),
        ]
        # glob for mpcache-*.bin in Scans
        for f in glob.glob(os.path.join(base, "Scans", "mpcache-*.bin")):
            try:
                scan_dirs.append(f)
            except Exception:
                pass
        sz = 0
        for sd in scan_dirs:
            if os.path.isfile(sd):
                try: sz += os.path.getsize(sd)
                except: pass
            elif os.path.isdir(sd):
                sz += dir_total(sd)
        if sz > 0:
            results.append(CacheItem(
                path=base, size=sz, provider="windows_extra",
                label="Windows Defender Scan Cache and Quarantine",
                safety=SafetyLevel.SAFE,
                extra={"type": "defender_cache", "rebuild_cost": "none",
                       "note": "Scan history and quarantine -- safe to delete"},
            ))
    return results


def _scan_xbox_cache(root: str) -> list[CacheItem]:
    """Xbox app cache and gaming packages under LocalAppData."""
    results = []
    base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Xbox")
    if os.path.isdir(base):
        sz = dir_total(base)
        if sz > 0:
            results.append(CacheItem(
                path=base, size=sz, provider="windows_extra",
                label="Xbox App Cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "xbox_cache", "rebuild_cost": "low"},
            ))
    # Check Xbox packages under Packages
    pkg_base = os.environ.get("LOCALAPPDATA", "")
    if pkg_base:
        pkg_dir = os.path.join(pkg_base, "Packages")
        if os.path.isdir(pkg_dir):
            for pkg in os.listdir(pkg_dir):
                pkgl = pkg.lower()
                if "xbox" in pkgl or "gaming" in pkgl or "gamingservices" in pkgl:
                    lc = os.path.join(pkg_dir, pkg, "LocalCache")
                    if os.path.isdir(lc):
                        sz = dir_total(lc)
                        if sz > 0:
                            results.append(CacheItem(
                                path=lc, size=sz, provider="windows_extra",
                                label=f"Xbox/{pkg[:30]} Cache",
                                safety=SafetyLevel.SAFE,
                                extra={"type": "xbox_pkg_cache", "rebuild_cost": "low"},
                            ))
    return results


def _scan_old_windows_backups(root: str) -> list[CacheItem]:
    """Old Windows installation backups (Windows.old, $Windows.~BT, etc.)."""
    results = []
    windir = os.environ.get("WINDIR", "C:\\Windows")
    candidates = [
        (os.path.join("C:\\", "Windows.old"), "Previous Windows Installation"),
        (os.path.join("C:\\", "$Windows.~BT"), "Windows Setup Temporary Files"),
        (os.path.join("C:\\", "$Windows.~WS"), "Windows Setup Temporary Files"),
        (os.path.join("C:\\", "$WinREAgent"), "Windows Recovery Agent"),
    ]
    for p, label in candidates:
        if os.path.isdir(p) and not os.path.samefile(p, windir):
            sz = dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="windows_extra",
                    label=label,
                    safety=SafetyLevel.SAFE,
                    extra={"type": "old_windows", "rebuild_cost": "none",
                           "note": "Leftover from Windows upgrade -- safe to delete if current system is stable"},
                ))
    return results


def _scan_ml_cache(root: str) -> list[CacheItem]:
    """ML/AI model caches — HuggingFace, Ollama, PyTorch, TensorFlow."""
    results = []
    user = os.environ.get("USERPROFILE", "C:\\Users\\default")
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    
    ml_paths = [
        # HuggingFace cache (can be 10-100 GB)
        (os.path.join(user, ".cache", "huggingface"), "HuggingFace Models/Data"),
        (os.path.join(local, "huggingface"), "HuggingFace Local"),
        # Ollama models
        (os.path.join(user, ".ollama", "models"), "Ollama Models"),
        (os.path.join(local, "Ollama"), "Ollama Cache"),
        # PyTorch
        (os.path.join(user, ".cache", "torch"), "PyTorch Hub Cache"),
        # TensorFlow
        (os.path.join(user, ".cache", "tensorflow"), "TensorFlow Cache"),
        # ONNX Runtime
        (os.path.join(local, "onnxruntime"), "ONNX Runtime Cache"),
        # LM Studio
        (os.path.join(user, ".lmstudio", "models"), "LM Studio Models"),
        # llama.cpp
        (os.path.join(user, ".cache", "llama.cpp"), "llama.cpp Cache"),
        # OpenCV
        (os.path.join(user, ".cache", "opencv"), "OpenCV Cache"),
        # pip ML packages
        (os.path.join(user, ".cache", "torch_extensions"), "Torch Extensions Cache"),
    ]
    for p, label in ml_paths:
        if os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="windows_extra",
                    label=label,
                    safety=SafetyLevel.CAUTION,
                    extra={"type": "ml_cache", "rebuild_cost": "high",
                           "note": f"ML model cache ({label}) -- large download if deleted"},
                ))
    return results


# -- Register all providers --
register("delivery_optimization", _scan_delivery_opt)
register("software_distribution", _scan_software_distribution)
register("store_cache", _scan_store_cache)
register("teams_cache", _scan_teams_cache)
register("onedrive_cache", _scan_onedrive_cache)
register("defender_cache", _scan_defender_scan_cache)
register("xbox_cache", _scan_xbox_cache)
register("old_windows_backups", _scan_old_windows_backups)
register("ml_cache", _scan_ml_cache)
