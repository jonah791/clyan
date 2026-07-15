"""Windows Installer 缓存扫描 — 分析 C:\Windows\Installer 下的 .msi / .msp 文件。

Installer 目录存储所有已安装程序的 MSI 安装源和补丁（MSP）。
- .msi 文件: 安装源，用于修复/卸载 → 谨慎，仅标记旧版本
- .msp 文件: Windows 补丁包，很多是已被替代的旧补丁 → 可安全清理
- .msi 历史目录: 已卸载程序的残留 → 安全可删

⚠ 风险警告: 清理 .msi 文件可能导致程序无法卸载。
建议只清理 >1 年的 .msp 补丁文件和已卸载程序的残留。
"""

import os
import time
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size


def _scan_windows_installer(root: str) -> list[CacheItem]:
    results = []
    installer_dir = r"C:\Windows\Installer"

    if not os.path.isdir(installer_dir):
        return results

    now = time.time()
    msp_total = 0
    msp_count = 0
    msp_old_count = 0
    msp_old_size = 0
    msi_old_count = 0
    msi_old_size = 0
    large_files = []

    try:
        for f in os.listdir(installer_dir):
            fp = os.path.join(installer_dir, f)
            try:
                if not os.path.isfile(fp):
                    continue
                fsize = os.path.getsize(fp)
                ext = f.lower()
                mtime = os.path.getmtime(fp)
                age_days = (now - mtime) / 86400

                if ext.endswith(".msp"):
                    msp_total += fsize
                    msp_count += 1
                    if age_days > 365:
                        msp_old_count += 1
                        msp_old_size += fsize
                elif ext.endswith(".msi"):
                    if age_days > 365:
                        msi_old_count += 1
                        msi_old_size += fsize
                elif ext.endswith(".msi") or ext.endswith(".mst") or ext.endswith(".pck"):
                    pass  # active installer files

                # Track large files for granular AI decision
                if fsize > 50_000_000 and (ext.endswith(".msp") or ext.endswith(".msi")):
                    large_files.append({
                        "name": f,
                        "size": fsize,
                        "age_days": int(age_days),
                        "type": "msp" if ext.endswith(".msp") else "msi",
                    })
            except Exception:
                pass
    except PermissionError:
        return results  # No admin access

    if msp_count == 0 and msi_old_count == 0:
        return results

    # Sort large files by size descending
    large_files.sort(key=lambda x: -x["size"])

    # ── 1. Old MSP patches (> 1 year) — safest to clean ──
    if msp_old_count > 0:
        results.append(CacheItem(
            path=installer_dir,
            provider="windows_installer",
            label=f"旧 Windows 补丁文件 (>1年, {msp_old_count} patches)",
            size=msp_old_size,
            safety=SafetyLevel.CAUTION,
            extra={
                "type": "old_msp_patches",
                "patch_count": msp_old_count,
                "total_msp_size": msp_total,
                "total_msp_count": msp_count,
                "old_patch_ratio": round(msp_old_count / max(msp_count, 1), 2),
                "note": f"旧 MSP 补丁（{msp_old_count}个，{format_size(msp_old_size)}），"
                        f"通常已被新补丁替代。删除后无法卸载对应更新",
                "rebuild_cost": "none",
            },
        ))

    # ── 2. Old MSI files (> 1 year) — caution ──
    if msi_old_count > 0:
        results.append(CacheItem(
            path=installer_dir,
            provider="windows_installer",
            label=f"旧安装源文件 (>1年, {msi_old_count} files)",
            size=msi_old_size,
            safety=SafetyLevel.CAUTION,
            extra={
                "type": "old_msi_files",
                "msi_old_count": msi_old_count,
                "note": f"旧 MSI 安装源（{msi_old_count}个，{format_size(msi_old_size)}），"
                        f"可能属于已卸载或不常用的程序。删除后无法卸载对应程序",
                "rebuild_cost": "none",
            },
        ))

    # ── 3. Top large individual files (for AI to inspect) ──
    for lf in large_files[:5]:
        label_type = "旧补丁" if lf["type"] == "msp" else "安装源"
        results.append(CacheItem(
            path=os.path.join(installer_dir, lf["name"]),
            provider="windows_installer",
            label=f"Windows Installer {label_type}: {lf['name'][:40]}",
            size=lf["size"],
            safety=SafetyLevel.CAUTION,
            extra={
                "type": f"{lf['type']}_large_file",
                "file_name": lf["name"],
                "age_days": lf["age_days"],
                "note": f"大文件 {format_size(lf['size'])}，{lf['age_days']} 天前修改。"
                        f"属于较旧{'补丁' if lf['type']=='msp' else '安装源'}"
                        if lf['age_days'] > 365 else f"较新文件，建议保留",
                "rebuild_cost": "none",
            },
        ))

    return results


register("windows_installer", _scan_windows_installer)
