"""未知缓存检测 — 扫描未被任何 provider 覆盖的目录。

原理:
  1. 列出 %USERPROFILE% 下所有 .xxx 目录和 %LOCALAPPDATA% 下所有应用目录
  2. 检查每个目录是否被现有 provider 覆盖
  3. 未覆盖的目录 → 报告为"未知缓存"，让 AI 自行判断
  
这就是"catch-all" provider —— 不再需要逐个添加 app 缓存。
"""

import os
import time
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size
from ...utils.dirtree import dir_total


# 已知被覆盖的目录名（对应现有 provider）
_KNOWN_COVERED = {
    # Node.js
    "npm-cache", "npm", "pnpm", "pnpm-store", "yarn", "yarn-cache",
    "bun", ".bun", ".yarn", ".pnpm-store",
    # Python
    "pip", "uv", "poetry", "conda", ".conda",
    # Rust
    "cargo", ".cargo", ".rustup",
    # Go
    "go", ".go", "go-build",
    # Java
    ".gradle", "gradle", ".m2", "maven",
    # .NET
    ".nuget", "nuget",
    # IDEs
    "Code", ".vscode", "JetBrains", "IntelliJ", "PyCharm", "WebStorm",
    "Rider", "CLion", "GoLand", "RustRover",
    # Browsers
    "Google", "Microsoft", "Mozilla", "Chromium", "Brave", "Vivaldi",
    "Opera", "Waterfox", "Pale Moon", "SeaMonkey",
    "Chrome", "Edge", "Firefox",
    # Windows
    "Microsoft", "Windows", "Temp", "WinSxS", "assembly",
    "Installer", "DriverStore", "FontCache", "Fonts",
    # App caches
    "Discord", "Slack", "Teams", "Zoom", "WeChat",
    "Spotify", "WhatsApp", "Obsidian", "Figma",
    "Flutter", ".dart_tool", ".pub-cache",
    "Android", ".android",
    "Docker", ".docker",
    # ML
    "huggingface", ".huggingface", ".ollama", "ollama",
    "pytorch", "tensorflow", "lm-studio", ".lm-studio",
    # Game
    "Steam", "EpicGamesLauncher", ".steam",
    ".minecraft", "Minecraft",
    # GPU
    "NVIDIA", "AMD", "Intel", "D3DSCache",
    # Caches we added
    ".cache", ".cloakbrowser", ".agents", ".claude", ".codex",
    ".astrbot_launcher", ".dartServer",
    "DeepChat", "BaiduYunKernel", "BaiduYunGuanjia",
    "DLSS Swapper", "BitComet",
    "DDNet", "AionUi",
    "BCUT", "@opencode-aidesktop-updater",
    "CrashDumps", "WER",
    "pip", "pip-deep",
    # Known non-cache
    "Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos",
    "Favorites", "Contacts", "Links", "Searches", "Saved Games",
    "OneDrive", ".ssh", ".gnupg", ".aws", ".gcp", ".azure",
    ".kube", ".config", ".local", ".git",
}


def _scan_unknown_caches(root: str) -> list[CacheItem]:
    """Scan for directories that no existing provider covers."""
    results = []
    up = os.environ.get("USERPROFILE", "")
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    now = time.time()

    # 1. Scan %USERPROFILE% for .xxx directories
    dot_dirs = []
    if up and os.path.isdir(up):
        try:
            for entry in os.listdir(up):
                if entry.startswith(".") and os.path.isdir(os.path.join(up, entry)):
                    name = entry.lstrip(".")
                    if name not in _KNOWN_COVERED:
                        dot_dirs.append(os.path.join(up, entry))
        except (PermissionError, OSError):
            pass

    # 2. Scan %LOCALAPPDATA% for unknown app dirs
    local_dirs = []
    if local and os.path.isdir(local):
        try:
            for entry in os.listdir(local):
                ep = os.path.join(local, entry)
                if os.path.isdir(ep):
                    name = entry.lower()
                    # Skip known covered, system, and dot dirs
                    if any(ignore in name for ignore in [k.lower() for k in _KNOWN_COVERED]):
                        continue
                    if entry.startswith("."):
                        continue
                    local_dirs.append(ep)
        except (PermissionError, OSError):
            pass

    # 3. Scan %APPDATA% for unknown app dirs  
    roam_dirs = []
    if roaming and os.path.isdir(roaming):
        try:
            for entry in os.listdir(roaming):
                ep = os.path.join(roaming, entry)
                if os.path.isdir(ep):
                    name = entry.lower()
                    if any(ignore in name for ignore in [k.lower() for k in _KNOWN_COVERED]):
                        continue
                    if entry.startswith("."):
                        continue
                    roam_dirs.append(ep)
        except (PermissionError, OSError):
            pass

    # Check size of each unknown dir (timeout after 5s total)
    check_start = time.time()
    for dirpath, source_label in (
        [(d, "~") for d in dot_dirs] +
        [(d, "LocalAppData") for d in local_dirs] +
        [(d, "AppData") for d in roam_dirs]
    ):
        if time.time() - check_start > 5:
            break  # Don't spend too long

        try:
            sz = dir_total(dirpath)
        except Exception:
            sz = 0

        if sz > 10_000_000:  # Only report >10 MB
            name = os.path.basename(dirpath)
            
            # ── 安全分级 ──
            # 根据目录名/路径判断是否可能是重要数据而非缓存
            is_likely_data = False
            data_reasons = []
            
            # 1. 名称包含 data/store/state 等关键词
            name_lower = name.lower()
            if any(k in name_lower for k in ["data", "store", "state", "db", "database",
                                               "backup", "archive", "sync", "index"]):
                is_likely_data = True
                data_reasons.append("目录名含 data/store 关键词")
            
            # 2. 在 Roaming 下 (通常是应用配置/数据，不是缓存)
            if source_label == "AppData":
                is_likely_data = True
                data_reasons.append("在 AppData/Roaming 下 (应用数据)")
            
            # 3. 包含已知数据子目录
            data_subdirs = ["data", "store", "state", "db", "database", "backup",
                           "config", "settings", "profile"]
            try:
                entries = [e.lower() for e in os.listdir(dirpath)[:50]]
                for ds in data_subdirs:
                    if ds in entries:
                        is_likely_data = True
                        data_reasons.append(f"含 '{ds}' 子目录")
                        break
            except Exception:
                pass
            
            # 4. 非常新的目录 (<30天) 可能正在使用中
            try:
                mtime = os.path.getmtime(dirpath)
                age_days = (time.time() - mtime) / 86400
            except Exception:
                age_days = -1
            is_recent = age_days < 30 and age_days >= 0
            
            if is_likely_data or is_recent:
                safety = SafetyLevel.UNSAFE if is_likely_data else SafetyLevel.CAUTION
                note_parts = ["未被现有 provider 覆盖的目录"]
                if is_likely_data:
                    note_parts.append(f"⚠ 可能包含重要数据:" + "; ".join(data_reasons))
                if is_recent:
                    note_parts.append(f"最近使用 ({int(age_days)} 天前)")
                note_parts.append(f"{format_size(sz)}，AI 需谨慎判断")
                
                results.append(CacheItem(
                    path=dirpath, size=sz,
                    provider="unknown_caches",
                    label=f"未知数据: {name} ({source_label}, {format_size(sz)})",
                    safety=safety,
                    extra={
                        "type": "unknown_app_data",
                        "source": source_label,
                        "dir_name": name,
                        "age_days": int(age_days) if age_days >= 0 else -1,
                        "data_warning": "; ".join(data_reasons) if data_reasons else None,
                        "note": " ".join(note_parts),
                        "rebuild_cost": "high",
                    },
                ))
            else:
                # 看起来像缓存 → SAFE
                note = f"未被覆盖的 {source_label} 目录。"
                if age_days >= 0:
                    note += f"{int(age_days)} 天未修改，"
                note += f"{format_size(sz)}。看起来像缓存，AI 可自行判断"
                
                results.append(CacheItem(
                    path=dirpath, size=sz,
                    provider="unknown_caches",
                    label=f"未知缓存: {name} ({source_label}, {format_size(sz)})",
                    safety=SafetyLevel.SAFE,
                    extra={
                        "type": "unknown_app_cache",
                        "source": source_label,
                        "dir_name": name,
                        "age_days": int(age_days) if age_days >= 0 else -1,
                        "note": note,
                        "rebuild_cost": "low",
                    },
                ))

    return results


register("unknown_caches", _scan_unknown_caches)
