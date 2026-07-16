"""Windows 事件日志扫描 -- .evtx 文件大小检测。

Windows 事件日志 (.evtx) 存储在 C:/Windows/System32/winevt/Logs，
会随着系统运行时间增长到数 GB。安全可清理（通过 wevtutil 或事件查看器）。
"""

import os
from . import CacheItem, SafetyLevel, register
from ...utils.size import format_size


def _scan_windows_logs(root: str) -> list[CacheItem]:
    results = []
    windir = os.environ.get("WINDIR", "C:\\Windows")
    log_dir = os.path.join(windir, "System32", "winevt", "Logs")
    if not os.path.isdir(log_dir):
        return results

    total_size = 0
    log_files = []
    try:
        for f in os.listdir(log_dir):
            if f.lower().endswith(".evtx"):
                fp = os.path.join(log_dir, f)
                sz = os.path.getsize(fp)
                total_size += sz
                log_files.append({"name": f, "size": sz})
    except (PermissionError, OSError):
        return results

    if not log_files:
        return results

    log_files.sort(key=lambda x: -x["size"])

    # Total
    results.append(CacheItem(
        path=log_dir,
        size=total_size,
        provider="windows_logs",
        label=f"Windows 事件日志 ({len(log_files)} files, {format_size(total_size)})",
        safety=SafetyLevel.SAFE,
        extra={
            "type": "event_logs_total",
            "file_count": len(log_files),
            "note": "Windows 事件日志 (.evtx)，可通过 wevtutil 清理。系统会自动重建",
            "rebuild_cost": "none",
        },
    ))

    # Individual large logs
    for lf in log_files[:5]:
        if lf["size"] > 10_000_000:
            log_name = lf["name"]
            results.append(CacheItem(
                path=os.path.join(log_dir, log_name),
                size=lf["size"],
                provider="windows_logs",
                label=f"事件日志: {log_name} ({format_size(lf['size'])})",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "event_log_file",
                    "file_name": log_name,
                    "note": f"大型事件日志 {log_name}，可通过 wevtutil cl 清理",
                    "rebuild_cost": "none",
                },
            ))

    return results


register("windows_logs", _scan_windows_logs)
