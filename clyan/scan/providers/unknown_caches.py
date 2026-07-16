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
            results.append(CacheItem(
                path=dirpath,
                size=sz,
                provider="unknown_caches",
                label=f"未知缓存: {name} ({source_label}, {format_size(sz)})",
                safety=SafetyLevel.CAUTION,  # Unknown → cautious
                extra={
                    "type": "unknown_app_cache",
                    "source": source_label,
                    "dir_name": name,
                    "note": f"未被现有 provider 覆盖的 {source_label} 目录。"
                           f"{format_size(sz)}，来源未知。AI 需自行判断是否可删",
                    "rebuild_cost": "unknown",
                },
            ))

    return results


register("unknown_caches", _scan_unknown_caches)
