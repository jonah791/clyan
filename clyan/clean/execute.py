import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..core.config import is_protected, SAFE_DELETE_DEFAULTS
from ..core.history import record_clean

_FAST_THRESHOLD = 100 * 1024 * 1024


def _delete_one(path: str, size: int, use_trash: bool, fast: bool) -> dict:
    try:
        if not os.path.exists(path):
            return {"path": path, "size": size, "success": False, "error": "not found"}

        is_dir = os.path.isdir(path)

        if fast and (size >= _FAST_THRESHOLD or is_dir):
            if is_dir:
                shutil.rmtree(path)
            else:
                os.remove(path)
            return {"path": path, "size": size, "success": True, "method": "direct"}
        elif use_trash:
            try:
                import send2trash
                send2trash.send2trash(path)
                return {"path": path, "size": size, "success": True, "method": "trash"}
            except ImportError:
                if is_dir:
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                return {"path": path, "size": size, "success": True, "method": "direct"}
        else:
            if is_dir:
                shutil.rmtree(path)
            else:
                os.remove(path)
            return {"path": path, "size": size, "success": True, "method": "direct"}
    except Exception as e:
        return {"path": path, "size": size, "success": False, "error": str(e)}


def delete_items(items: list[dict], use_trash: bool = True, fast: bool = False) -> dict:
    start = time.time()
    total = len(items)
    results = [None] * total
    total_freed = 0
    success_count = 0
    fail_count = 0
    errors = []

    work_items = []
    for item in items:
        path = item.get("path", "")
        size = item.get("size", 0)
        if is_protected(path):
            errors.append(f"skipped protected path: {path}")
            continue
        work_items.append((path, size))

    n_workers = min(8, len(work_items) or 1)

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        futures = {
            pool.submit(_delete_one, path, size, use_trash, fast): (path, size)
            for path, size in work_items
        }
        for future in as_completed(futures):
            res = future.result()
            if res["success"]:
                success_count += 1
                total_freed += res["size"]
            else:
                fail_count += 1
                if res.get("error"):
                    errors.append(f"failed to delete {res['path']}: {res['error']}")
            results.append(res)

    elapsed = time.time() - start
    op_id = record_clean(items, total_freed)

    return {
        "operation_id": op_id,
        "success_count": success_count,
        "fail_count": fail_count,
        "total_freed": total_freed,
        "total_freed_human": _fmt(total_freed),
        "use_trash": use_trash,
        "fast_mode": fast,
        "elapsed_seconds": round(elapsed, 1),
        "workers": n_workers,
        "results": results,
        "errors": errors,
    }


def _fmt(size: int) -> str:
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    v = float(size)
    while v >= 1024 and idx < len(suffixes) - 1:
        v /= 1024
        idx += 1
    return f"{v:.2f} {suffixes[idx]}"
