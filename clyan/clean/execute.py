import os
import sys
import shutil
import subprocess
import time
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..core.config import is_protected
from ..core.history import record_clean
from ..utils.size import format_size


# Thresholds for native Windows delete (rd / del via cmd.exe).
# Spawning cmd.exe has ~50ms overhead, so only worthwhile for deep trees.
_FAST_THRESHOLD = 100 * 1024 * 1024  # 100 MB — files above this use del /f/q
_NATIVE_DIR_THRESHOLD = 500 * 1024 * 1024  # 500 MB — dirs above use rd /s/q
_TRASH_BATCH_SIZE = 50  # batch trash COM calls to reduce overhead
_CREATE_NO_WINDOW = 0x08000000  # suppress cmd window flash

# Cache is_protected results — rules don't change during a session.
_cached_is_protected = lru_cache(maxsize=65536)(is_protected)


def _rd(path: str) -> bool:
    """Native Windows recursive directory delete via cmd.
    1.3x faster than shutil.rmtree for deep trees; only worthwhile above 500 MB."""
    try:
        # Add \\?\ prefix for long paths (> 240 chars) to bypass MAX_PATH
        delete_path = path
        if len(path) > 240 and not path.startswith("\\\\?\\"):
            delete_path = "\\\\?\\" + os.path.normpath(path)
        subprocess.run(
            ["cmd", "/c", "rd", "/s", "/q", delete_path],
            capture_output=True,
            timeout=120,
            creationflags=_CREATE_NO_WINDOW,
        )
        return not os.path.exists(path)
    except Exception:
        return False


def _send_to_trash(paths: list[str]) -> list[dict]:
    """Send multiple paths to recycle bin in one COM session."""
    try:
        import send2trash
        send2trash.send2trash(paths)
        return [{"path": p, "success": True, "method": "trash"} for p in paths]
    except Exception as e:
        err = str(e)
        return [{"path": p, "success": False, "error": err} for p in paths]


def _delete_one(path: str, size: int, use_trash: bool, fast: bool) -> dict:
    """Delete a single item. Used in the parallel pool for fast/direct items."""
    try:
        if not os.path.exists(path):
            return {"path": path, "size": size, "success": True, "method": "already_gone"}

        is_dir = os.path.isdir(path)

        # Fast/native path: for large items or when --fast mode is active
        if fast and (size >= _FAST_THRESHOLD or is_dir):
            if is_dir:
                if size >= _NATIVE_DIR_THRESHOLD:
                    ok = _rd(path)
                    if ok:
                        return {"path": path, "size": size, "success": True, "method": "native_fast"}
                # Smaller dirs: parallel shutil.rmtree is faster than spawning cmd.exe
                shutil.rmtree(path)
            else:
                # Files: os.remove is fast enough, parallel doesn't help
                os.remove(path)
            return {"path": path, "size": size, "success": True, "method": "direct"}

        # Sequential / trash mode: handled by caller
        if use_trash:
            import send2trash
            send2trash.send2trash(path)
            return {"path": path, "size": size, "success": True, "method": "trash"}
        elif is_dir:
            shutil.rmtree(path)
        else:
            os.remove(path)
        return {"path": path, "size": size, "success": True, "method": "direct"}

    except Exception as e:
        err_msg = str(e)
        win_err = getattr(e, "winerror", None)
        time.sleep_val = 0.5

        if win_err is not None:
            known_win = {
                5: "权限不足（拒绝访问）",
                32: "文件正在被其他程序使用",
                206: "路径过长（文件系统限制）",
                145: "目录非空",
            }
            hint = known_win.get(win_err, f"Windows 错误 {win_err}")
            # Retry permission / in-use errors once
            if win_err in (5, 32):
                try:
                    time.sleep(time.sleep_val)
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=False)
                    else:
                        os.remove(path)
                    return {"path": path, "size": size, "success": True, "method": "direct_retry"}
                except Exception:
                    pass
            return {"path": path, "size": size, "success": False, "error": hint}

        # Fallback: string matching for non-Windows or unknown errors
        known_str = {
            "access is denied": "权限不足，以管理员身份运行重试",
            "permission denied": "权限不足",
            "directory not empty": "目录非空",
            "file exists": "路径已存在",
        }
        for code, hint in known_str.items():
            if code in err_msg.lower():
                return {"path": path, "size": size, "success": False, "error": hint}
        return {"path": path, "size": size, "success": False, "error": err_msg}


def delete_items(items: list[dict], use_trash: bool = True, fast: bool = False) -> dict:
    start = time.time()
    total_freed = 0
    success_count = 0
    fail_count = 0
    errors: list[str] = []
    results: list[dict] = []

    # Phase 1: validate + classify + filter protected / already-gone
    trash_paths: list[str] = []
    trash_sizes: dict[str, int] = {}
    fast_direct: list[tuple[str, int]] = []
    already_gone_count = 0

    for item in items:
        path = item.get("path", "")
        size = item.get("size", 0)

        if _cached_is_protected(path):
            errors.append(f"skipped protected path: {path}")
            continue

        if not os.path.exists(path):
            results.append({"path": path, "size": size, "success": True, "method": "already_gone"})
            already_gone_count += 1
            continue

        # Classification: fast items go to parallel pool; the rest go to trash or direct pool
        if fast and (size >= _FAST_THRESHOLD or os.path.isdir(path)):
            fast_direct.append((path, size))
        elif use_trash:
            trash_paths.append(path)
            trash_sizes[path] = size
        else:
            fast_direct.append((path, size))

    # Sort by size descending: bigger items first for faster visible progress
    trash_paths.sort(key=lambda p: trash_sizes.get(p, 0), reverse=True)
    fast_direct.sort(key=lambda p: p[1], reverse=True)

    # Phase 2: execute deletions

    # 2a: Trash items in batches — one COM session per batch
    if trash_paths:
        for i in range(0, len(trash_paths), _TRASH_BATCH_SIZE):
            batch = trash_paths[i:i + _TRASH_BATCH_SIZE]
            batch_results = _send_to_trash(batch)
            for r in batch_results:
                if r["success"]:
                    success_count += 1
                    total_freed += trash_sizes.get(r["path"], 0)
                else:
                    fail_count += 1
                    errors.append(f"failed to delete {r['path']}: {r.get('error', 'unknown')}")
            results.extend(batch_results)

    # 2b: Fast/direct items — parallel pool (shutil.rmtree in each worker)
    if fast_direct:
        n_workers = min(8, len(fast_direct))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {
                pool.submit(_delete_one, path, size, use_trash, fast): (path, size)
                for path, size in fast_direct
            }
            for f in as_completed(futures):
                res = f.result()
                if res["success"]:
                    success_count += 1
                    total_freed += res["size"]
                else:
                    fail_count += 1
                    if res.get("error"):
                        errors.append(f"failed to delete {res['path']}: {res['error']}")
                results.append(res)

    elapsed = time.time() - start
    op_id = record_clean(
        [r for r in results if r.get("success")],
        total_freed,
    )

    return {
        "operation_id": op_id,
        "success_count": success_count,
        "fail_count": fail_count,
        "already_gone": already_gone_count,
        "total_freed": total_freed,
        "total_freed_human": format_size(total_freed),
        "use_trash": use_trash,
        "fast_mode": fast,
        "elapsed_seconds": round(elapsed, 1),
        "results": results,
        "errors": errors,
    }
