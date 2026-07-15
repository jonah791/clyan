"""DISM 深度清理集成 — 建议 DISM 命令安全释放 WinSxS/DriverStore 空间。

不作为扫描 provider 运行（不从磁盘扫描文件），而是作为"清理建议"提供，
让 AI 知道可以通过运行 DISM 命令来额外释放空间。

本 provider 返回"可执行项"——每个 item 对应一个 DISM 命令及其预估释放量。
"""

import os
import subprocess
import re
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size


def _scan_dism_cleanup(root: str) -> list[CacheItem]:
    results = []

    # ── 1. WinSxS 组件清理 ──
    winsxs_dir = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "WinSxS")
    if os.path.isdir(winsxs_dir):
        results.append(CacheItem(
            path=winsxs_dir,
            size=0,  # size unknown until DISM runs
            provider="dism_cleanup",
            label="DISM WinSxS 组件清理",
            safety=SafetyLevel.SAFE,
            extra={
                "type": "dism_component_cleanup",
                "command": f"DISM /Online /Cleanup-Image /StartComponentCleanup",
                "requires_admin": True,
                "note": "使用 DISM 清理 WinSxS 组件存储中替代的组件版本。"
                       "安全，无副作用。运行后约 30% 的 WinSxS 可被释放",
                "rebuild_cost": "none",
                "estimated_savings_hint": "~30% of WinSxS",
            },
        ))

    # ── 2. WinSxS 重置基数 ──
    results.append(CacheItem(
        path=winsxs_dir,
        size=0,
        provider="dism_cleanup",
        label="DISM WinSxS 重置基数",
        safety=SafetyLevel.CAUTION,
        extra={
            "type": "dism_reset_base",
            "command": f"DISM /Online /Cleanup-Image /StartComponentCleanup /ResetBase",
            "requires_admin": True,
            "note": "重置 WinSxS 基数。删除所有旧组件版本，只保留当前版本。"
                   "⚠ 清理后无法卸载当前累积更新",
            "rebuild_cost": "none",
        },
    ))

    # ── 3. DriverStore 旧驱动清理 ──
    results.append(CacheItem(
        path=os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "System32", "DriverStore", "FileRepository"),
        size=0,
        provider="dism_cleanup",
        label="DISM 旧驱动包清理",
        safety=SafetyLevel.SAFE,
        extra={
            "type": "dism_driver_cleanup",
            "command": "pnputil /enum-drivers  # 查看驱动列表\n"
                      "pnputil /delete-driver <published_name>  # 删除指定驱动",
            "requires_admin": True,
            "note": "使用 pnputil 列出并删除旧版驱动。DriverStore 中通常有"
                   "多个旧版显卡/声卡/网卡驱动，每个 100-500 MB",
            "rebuild_cost": "none",
            "requires_more_info": True,
        },
    ))

    # ── 4. Delivery Optimization 深度清理 ──
    do_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"),
                           "ServiceProfiles", "NetworkService", "AppData",
                           "Local", "Microsoft", "Windows", "DeliveryOptimization", "Cache")
    results.append(CacheItem(
        path=do_path,
        size=0,
        provider="dism_cleanup",
        label="Delivery Optimization 深度清理",
        safety=SafetyLevel.SAFE,
        extra={
            "type": "dism_delivery_opt",
            "command": "net stop DoSvc\n"
                      f'del /f /q "{do_path}"\\*.* 2>nul\n'
                      "net start DoSvc",
            "requires_admin": True,
            "note": "停止 Delivery Optimization 服务 → 清空缓存 → 重新启动。"
                   "P2P 更新缓存，安全可删",
            "rebuild_cost": "none",
        },
    ))

    return results


register("dism_cleanup", _scan_dism_cleanup)
