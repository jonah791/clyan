"""零碎小文件扫描 — modclean 模式的应用。

不是"找大文件"，是"找无用的小文件"——那些单个不占多少空间，
但成千上万积累起来就很可观的零碎垃圾。

扫描策略 (modclean 模式):
  1. 定义已知无用文件名/扩展名列表
  2. 遍历用户目录 (max_depth=8)
  3. 跳过系统目录 / node_modules / .git
  4. 只检查 <1MB 的文件
  5. 只标记 >90 天未修改的文件
  6. 按类型分组输出
"""

import os
import time
from . import CacheItem, SafetyLevel, register
from ...utils.scanner_base import safe_walk
from ...utils.size import format_size


# ── 已知安全可删的小文件模式 ─────────────────────────
# 这些文件在任何目录下出现都可以安全删除。
# 来源于 modclean (精确文件名) + Winapp2 (ext+path) + BleachBit 经验。

_SMALL_WASTE_FILES = {
    # Windows shell 残留
    "desktop.ini",
    "thumbs.db",
    "ehthumbs.db",
    "thumbs.db:encryptable",
    # 编辑器/IDE 临时文件
    "~$"  # Office 临时文件 (前缀匹配)
}

_SMALL_WASTE_EXTS = {
    # 日志文件（通常可删）
    ".log", ".journal",
    # 备份/旧文件
    ".bak", ".old", ".tmp",
    # Windows 转储
    ".dmp", ".mdmp", ".hdmp", ".dump",
    # 性能跟踪
    ".etl", ".wpr", ".blg",
    # 缓存索引
    ".idx", ".index",
    # Office 临时
    ".tmp",
}

# 跳过的目录名
_SKIP_WASTE_DIRS = {
    "node_modules", ".git", ".svn", ".hg",
    "Windows", "Program Files", "Program Files (x86)",
    "System32", "SysWOW64",
    "WinSxS", "assembly",
}

_BASE_SKIP = {
    "$Recycle.Bin", "System Volume Information", "Recovery",
    "ProgramData", "All Users", "Default", "Default User",
    "Microsoft.NET", "Assembly", "WinSxS",
}


def _scan_small_files(root: str) -> list[CacheItem]:
    """Scan for small waste files scattered across the filesystem."""
    results = []
    now = time.time()

    # Group findings
    by_type: dict[str, dict] = {}
    total_files = 0
    total_size = 0

    try:
        for dirpath, dirs, files in safe_walk(root, max_depth=4):
            # Skip internal dirs
            base = os.path.basename(dirpath)
            dirname = os.path.basename(os.path.dirname(dirpath))

            # Skip system/protected dirs
            skip = False
            # Skip well-known large non-waste paths
            parts = dirpath.split(os.sep)
            # Skip deep AppData paths (deep caches), but keep Temp and Recent
            if "AppData" in parts and len(parts) > 5:
                skip = True
                # In AppData\Local, only scan Temp and well-known cache dirs
                skip = True
            # Skip standard system dirs
            for skip_dir in _SKIP_WASTE_DIRS:
                if skip_dir in dirpath.split(os.sep):
                    skip = True
                    break
            if skip:
                dirs.clear()
                continue

            for f in files:
                fpath = os.path.join(dirpath, f)
                try:
                    fstat = os.stat(fpath)
                except (OSError, PermissionError):
                    continue

                # Only small files (< 1 MB)
                if fstat.st_size > 1_000_000:
                    continue

                # Only old files (> 90 days)
                age = (now - fstat.st_mtime) / 86400
                if age < 90:
                    continue

                name_lower = f.lower()
                matched = False
                waste_type = ""

                # Check exact filename match
                if name_lower in _SMALL_WASTE_FILES:
                    matched = True
                    waste_type = name_lower
                # Check prefix match (e.g. ~$ files)
                elif name_lower.startswith("~$"):
                    matched = True
                    waste_type = "office_temp"
                # Check extension match
                else:
                    ext = os.path.splitext(name_lower)[1]
                    if ext in _SMALL_WASTE_EXTS:
                        # Skip .log files in project directories
                        if ext == ".log" and ("node_modules" in dirpath or ".git" in dirpath):
                            continue
                        matched = True
                        waste_type = ext.lstrip(".") + "_files"

                if matched:
                    total_files += 1
                    total_size += fstat.st_size
                    by_type.setdefault(waste_type, {"count": 0, "size": 0, "paths": []})
                    by_type[waste_type]["count"] += 1
                    by_type[waste_type]["size"] += fstat.st_size
                    if len(by_type[waste_type]["paths"]) < 5:
                        by_type[waste_type]["paths"].append(fpath)
    except Exception:
        pass

    if total_files == 0:
        return results

    # Create label map
    label_map = {
        "desktop.ini": "Desktop.ini 残留",
        "thumbs.db": "Thumbs.db 缓存",
        "ehthumbs.db": "EhThumbs.db 缓存",
        "office_temp": "Office 临时文件 (~$)",
        "log_files": "旧日志文件 (.log)",
        "bak_files": "备份残留 (.bak)",
        "old_files": "旧版本残留 (.old)",
        "tmp_files": "临时文件 (.tmp)",
        "dmp_files": "崩溃转储 (.dmp)",
        "mdmp_files": "迷你转储 (.mdmp)",
        "hdmp_files": "堆转储 (.hdmp)",
        "dump_files": "系统转储 (.dump)",
        "etl_files": "性能跟踪 (.etl)",
        "wpr_files": "WPR 跟踪 (.wpr)",
        "blg_files": "性能计数器 (.blg)",
        "idx_files": "缓存索引 (.idx)",
        "index_files": "索引文件 (.index)",
        "journal_files": "日志文件 (.journal)",
    }

    for waste_type, data in sorted(by_type.items(), key=lambda x: -x[1]["size"]):
        label = label_map.get(waste_type, f"{waste_type} 文件")
        results.append(CacheItem(
            path=data["paths"][0] if data["paths"] else root,
            size=data["size"],
            provider="small_files",
            label=f"{label} ({data['count']} 文件, {format_size(data['size'])})",
            safety=SafetyLevel.SAFE,
            extra={
                "type": f"small_waste_{waste_type}",
                "file_count": data["count"],
                "sample_paths": data["paths"],
                "note": f"{data['count']} 个 {waste_type} 文件共 {format_size(data['size'])}，散布在系统中。安全可删",
                "rebuild_cost": "none",
            },
        ))

    return results


register("small_files", _scan_small_files)
