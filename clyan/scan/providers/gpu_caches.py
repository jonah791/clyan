"""GPU/显卡/着色器缓存 + 游戏缓存 + 系统还原点。

BleachBit 覆盖但 Clyan 尚未覆盖的高价值区域:
  - DirectX Shader Cache: 游戏和图形应用累积的着色器缓存 (GB级)
  - NVIDIA DXCache/GLCache: N 卡驱动着色器缓存
  - Steam 着色器缓存: Steam 预编译着色器
  - 系统还原点: 可通过 vssadmin 管理
"""

import os
import subprocess
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size
from ...utils.dirtree import dir_total


def _scan_gpu_caches(root: str) -> list[CacheItem]:
    results = []
    up = os.environ.get("USERPROFILE", "")
    local = os.environ.get("LOCALAPPDATA", "")

    # ── DirectX Shader Cache ──
    dxc = os.path.join(local, "D3DSCache")
    if os.path.isdir(dxc):
        sz = dir_total(dxc)
        if sz > 1_000_000:
            results.append(CacheItem(
                path=dxc, size=sz, provider="gpu_caches",
                label=f"DirectX 着色器缓存 ({format_size(sz)})",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "directx_shader_cache",
                    "note": "DirectX 着色器缓存。游戏运行时自动重建，安全可删",
                    "rebuild_cost": "low",
                },
            ))

    # ── NVIDIA Shader Cache ──
    nv_dirs = [
        os.path.join(local, "NVIDIA", "DXCache"),
        os.path.join(local, "NVIDIA", "GLCache"),
        os.path.join(local, "NVIDIA Corporation", "NV_Cache"),
    ]
    for nvd in nv_dirs:
        if os.path.isdir(nvd):
            sz = dir_total(nvd)
            if sz > 1_000_000:
                label_name = os.path.basename(nvd)
                results.append(CacheItem(
                    path=nvd, size=sz, provider="gpu_caches",
                    label=f"NVIDIA {label_name} ({format_size(sz)})",
                    safety=SafetyLevel.SAFE,
                    extra={
                        "type": f"nvidia_{label_name.lower()}",
                        "note": "NVIDIA 驱动着色器缓存。驱动更新时可安全删除",
                        "rebuild_cost": "low",
                    },
                ))

    # ── AMD Shader Cache ──
    amd = os.path.join(local, "AMD", "DXCache")
    if os.path.isdir(amd):
        sz = dir_total(amd)
        if sz > 1_000_000:
            results.append(CacheItem(
                path=amd, size=sz, provider="gpu_caches",
                label=f"AMD 着色器缓存 ({format_size(sz)})",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "amd_shader_cache",
                    "note": "AMD 驱动着色器缓存。安全可删",
                    "rebuild_cost": "low",
                },
            ))

    # ── Intel GPU Cache ──
    intel_dir = os.path.join(local, "Intel", "ShaderCache")
    if os.path.isdir(intel_dir):
        sz = dir_total(intel_dir)
        if sz > 1_000_000:
            results.append(CacheItem(
                path=intel_dir, size=sz, provider="gpu_caches",
                label=f"Intel 着色器缓存 ({format_size(sz)})",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "intel_shader_cache",
                    "note": "Intel GPU 着色器缓存。安全可删",
                    "rebuild_cost": "low",
                },
            ))

    # ── Steam Shader Pre-Cache ──
    steam_dirs = [
        os.path.join(up, "AppData", "Local", "Steam", "htmlcache"),
        os.path.join(up, ".steam", "steam", "shader_cache"),
    ]
    for sd in steam_dirs:
        if os.path.isdir(sd):
            sz = dir_total(sd)
            if sz > 1_000_000:
                results.append(CacheItem(
                    path=sd, size=sz, provider="gpu_caches",
                    label=f"Steam 缓存 ({format_size(sz)})",
                    safety=SafetyLevel.SAFE,
                    extra={
                        "type": "steam_cache",
                        "note": "Steam web/着色器缓存。安全可删，Steam 会重新下载",
                        "rebuild_cost": "low",
                    },
                ))

    # ── Epic Games Launcher Cache ──
    epic = os.path.join(local, "EpicGamesLauncher", "Saved", "webcache")
    if os.path.isdir(epic):
        sz = dir_total(epic)
        if sz > 1_000_000:
            results.append(CacheItem(
                path=epic, size=sz, provider="gpu_caches",
                label=f"Epic 启动器缓存 ({format_size(sz)})",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "epic_cache",
                    "note": "Epic Games Launcher web 缓存。安全可删",
                    "rebuild_cost": "low",
                },
            ))

    return results


def _scan_system_restore(root: str) -> list[CacheItem]:
    """Check System Restore point disk usage via vssadmin."""
    results = []
    try:
        result = subprocess.run(
            ["vssadmin", "list", "shadowstorage"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return results

        # Parse output for "Used Shadow Copy Storage space"
        used_bytes = 0
        allocated_bytes = 0
        for line in result.stdout.splitlines():
            line = line.strip()
            if "Used Shadow Copy Storage space" in line:
                # Format: "Used Shadow Copy Storage space: 12.5 GB (13421772800 bytes)"
                import re
                m = re.search(r'\((\d+)\s*bytes\)', line, re.IGNORECASE)
                if m:
                    used_bytes += int(m.group(1))
            if "Allocated Shadow Copy Storage space" in line:
                m = re.search(r'\((\d+)\s*bytes\)', line, re.IGNORECASE)
                if m:
                    allocated_bytes += int(m.group(1))

        if used_bytes > 0:
            results.append(CacheItem(
                path="System Restore", size=used_bytes,
                provider="gpu_caches",
                label=f"系统还原点 ({format_size(used_bytes)})",
                safety=SafetyLevel.CAUTION,
                extra={
                    "type": "system_restore",
                    "allocated_bytes": allocated_bytes,
                    "note": "系统还原点。可通过 'vssadmin delete shadows /all' 清理。"
                           "清理后无法恢复系统到旧状态",
                    "rebuild_cost": "none",
                    "command_hint": "vssadmin delete shadows /all",
                },
            ))
    except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
        pass

    return results


def _scan_gpu_caches_full(root: str) -> list[CacheItem]:
    """Combined GPU + system restore scan."""
    results = _scan_gpu_caches(root)
    results.extend(_scan_system_restore(root))
    return results


register("gpu_caches", _scan_gpu_caches_full)
