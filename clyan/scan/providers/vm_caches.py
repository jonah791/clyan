"""虚拟机/WSL 缓存检测 — Docker + WSL2 + VM 磁盘空间。

Docker 和 WSL2 的虚拟磁盘文件（vhdx/vmdk/vdi）是著名的"黑洞"——
容器镜像和 WSL distro 会占用大量磁盘但不会被普通文件扫描检测到。
"""

import os
import subprocess
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size
from ...utils.dirtree import dir_total


def _scan_vm_caches(root: str) -> list[CacheItem]:
    results = []
    up = os.environ.get("USERPROFILE", "")

    # ── Docker 悬空镜像 ──
    docker_exe = None
    for candidate in ["docker", "docker.exe",
                       r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"]:
        try:
            subprocess.run([candidate, "--version"], capture_output=True, timeout=5,
                          creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            docker_exe = candidate
            break
        except (FileNotFoundError, Exception):
            continue

    if docker_exe:
        # Check dangling images
        try:
            result = subprocess.run(
                [docker_exe, "images", "--filter", "dangling=true", "--format", "{{.ID}} {{.Size}}"],
                capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().splitlines()
                # Parse sizes
                total_size = 0
                for line in lines:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        sz_str = parts[-1]
                        try:
                            if "GB" in sz_str:
                                total_size += int(float(sz_str.replace("GB", "")) * 1e9)
                            elif "MB" in sz_str:
                                total_size += int(float(sz_str.replace("MB", "")) * 1e6)
                            elif "kB" in sz_str:
                                total_size += int(float(sz_str.replace("kB", "")) * 1e3)
                            else:
                                total_size += int(sz_str)
                        except ValueError:
                            pass
                if total_size > 0:
                    results.append(CacheItem(
                        path="Docker", size=total_size, provider="vm_caches",
                        label=f"Docker 悬空镜像 ({len(lines)} images, {format_size(total_size)})",
                        safety=SafetyLevel.SAFE,
                        extra={
                            "type": "docker_dangling",
                            "image_count": len(lines),
                            "command_hint": "docker image prune -f",
                            "note": "无标签/无引用的 Docker 镜像。'docker image prune -f' 安全清理",
                            "rebuild_cost": "low",
                        },
                    ))
        except Exception:
            pass

        # Check stopped containers
        try:
            result = subprocess.run(
                [docker_exe, "container", "ls", "--filter", "status=exited", "--format", "{{.ID}} {{.Size}}"],
                capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
            )
            if result.returncode == 0 and result.stdout.strip():
                lines = result.stdout.strip().splitlines()
                results.append(CacheItem(
                    path="Docker", size=0, provider="vm_caches",
                    label=f"已停止 Docker 容器 ({len(lines)} containers)",
                    safety=SafetyLevel.SAFE,
                    extra={
                        "type": "docker_stopped",
                        "container_count": len(lines),
                        "command_hint": "docker container prune -f",
                        "note": "已停止的容器。'docker container prune -f' 安全清理",
                        "rebuild_cost": "none",
                    },
                ))
        except Exception:
            pass

    # ── WSL2 虚拟磁盘 ──
    # WSL2 使用 VHDX 文件，不占用用户目录空间。
    # 但 WSL2 的 ext4.vhdx 会自动增长但不会自动缩小。
    # 通过 wsl --shutdown + diskpart compact 可以压缩。
    wsl_exists = False
    try:
        result = subprocess.run(
            ["wsl", "--status"], capture_output=True, text=True, timeout=5, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        wsl_exists = result.returncode == 0
    except (FileNotFoundError, Exception):
        pass

    if wsl_exists:
        # Check VHDX size
        vhdx_paths = [
            os.path.join(up, "AppData", "Local", "Packages", p, "LocalState", "ext4.vhdx")
            for p in os.listdir(os.path.join(up, "AppData", "Local", "Packages"))
            if os.path.isdir(os.path.join(up, "AppData", "Local", "Packages", p))
            and ("Canonical" in p or "Ubuntu" in p or "wsl" in p.lower())
        ] if os.path.isdir(os.path.join(up, "AppData", "Local", "Packages")) else []

        for vhdx in vhdx_paths:
            if os.path.isfile(vhdx):
                sz = os.path.getsize(vhdx)
                if sz > 100_000_000:  # >100 MB
                    results.append(CacheItem(
                        path=vhdx, size=sz, provider="vm_caches",
                        label=f"WSL2 虚拟磁盘 ({format_size(sz)})",
                        safety=SafetyLevel.CAUTION,
                        extra={
                            "type": "wsl2_vhdx",
                            "note": "WSL2 ext4.vhdx 自动增长不自动缩小。"
                                   "压缩方法: wsl --shutdown → diskpart compact vhdx",
                            "rebuild_cost": "none",
                        },
                    ))

    # ── VirtualBox VM 缓存 ──
    vb_dir = os.path.join(up, "VirtualBox VMs")
    if os.path.isdir(vb_dir):
        for vm in os.listdir(vb_dir):
            vm_path = os.path.join(vb_dir, vm)
            if os.path.isdir(vm_path):
                sz = dir_total(vm_path)
                if sz > 1_000_000_000:  # >1 GB
                    results.append(CacheItem(
                        path=vm_path, size=sz, provider="vm_caches",
                        label=f"VirtualBox VM: {vm}",
                        safety=SafetyLevel.CAUTION,
                        extra={
                            "type": "virtualbox_vm",
                            "note": "VirtualBox 虚拟机。清理前请确认不再需要",
                            "rebuild_cost": "high",
                        },
                    ))

    return results


register("vm_caches", _scan_vm_caches)
