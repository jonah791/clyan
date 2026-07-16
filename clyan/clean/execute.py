import os
import sys
import shutil
import subprocess
import time
import ctypes
import ctypes.wintypes
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..core.config import is_protected
from ..core.history import record_clean
from ..utils.size import format_size


def _get_disk_free(path: str) -> tuple[int, int, int]:
    root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
    try:
        fba = ctypes.c_ulonglong(0)
        tb = ctypes.c_ulonglong(0)
        tfb = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            root, ctypes.byref(fba), ctypes.byref(tb), ctypes.byref(tfb),
        )
        t = tb.value
        f = fba.value
        return t, f, t - f
    except Exception:
        return 0, 0, 0


_CREATE_NO_WINDOW = 0x08000000
_TRASH_BATCH_SIZE = 50


def _send_to_trash(paths: list[str]) -> list[dict]:
    try:
        import send2trash
        send2trash.send2trash(paths)
        return [{"path": p, "success": True, "method": "trash"} for p in paths]
    except Exception as e:
        err = str(e)
        return [{"path": p, "success": False, "error": err} for p in paths]


def _delete_one(path: str, size: int, method: str = "auto") -> dict:
    """Delete a single item. Method: trash, direct, native, or auto."""
    try:
        if not os.path.exists(path):
            return {"path": path, "size": size, "success": True, "method": "already_gone"}
        is_dir = os.path.isdir(path)

        if method == "trash":
            import send2trash
            send2trash.send2trash(path)
            return {"path": path, "size": size, "success": True, "method": "trash"}

        elif method == "native":
            cmd = ["cmd", "/c", "rd", "/s", "/q", path] if is_dir else ["cmd", "/c", "del", "/f", "/q", path]
            subprocess.run(cmd, capture_output=True, timeout=120, creationflags=_CREATE_NO_WINDOW)
            return {"path": path, "size": size, "success": not os.path.exists(path), "method": "native"}

        elif method == "direct":
            if is_dir:
                shutil.rmtree(path, ignore_errors=False)
            else:
                os.remove(path)
            return {"path": path, "size": size, "success": not os.path.exists(path), "method": "direct"}

        else:  # auto — heuristic
            if is_dir:
                subprocess.run(["cmd", "/c", "rd", "/s", "/q", path],
                               capture_output=True, timeout=120, creationflags=_CREATE_NO_WINDOW)
            else:
                try:
                    os.remove(path)
                except Exception:
                    subprocess.run(["cmd", "/c", "del", "/f", "/q", path],
                                   capture_output=True, timeout=30, creationflags=_CREATE_NO_WINDOW)
            return {"path": path, "size": size, "success": not os.path.exists(path), "method": "auto"}

    except Exception as e:
        win_err = getattr(e, "winerror", None)
        if win_err is not None:
            known = {5: "insufficient permissions", 32: "file in use",
                     206: "path too long", 145: "dir not empty",
                     123: "invalid path syntax", 267: "invalid dir"}
            return {"path": path, "size": size, "success": False,
                    "error": known.get(win_err, f"Windows error {win_err}")}
        return {"path": path, "size": size, "success": False, "error": str(e)}


def delete_items(items: list[dict], use_trash: bool = True, fast: bool = False) -> dict:
    """Execute deletion. AI chooses per-item strategy via `method` field.
    
    Each item can have:
      - `method`: "trash", "direct", "native", "auto" (default)
      - `path`, `size`
    
    `use_trash` / `fast` are fallbacks when method is "auto".
    Protected-path blocking removed — AI decides; warnings returned in response.
    """
    start = time.time()
    ref_path = items[0].get("path", ".") if items else "."
    _, before_free, _ = _get_disk_free(ref_path)

    total_freed = 0
    success_count = 0
    fail_count = 0
    errors: list[str] = []
    results: list[dict] = []
    trash_paths: list[str] = []
    trash_sizes: dict[str, int] = {}
    direct_items: list[tuple[str, int, str]] = []
    already_gone_count = 0
    protected_warned: list[str] = []

    for item in items:
        path = item.get("path", "")
        size = item.get("size", 0)
        method = item.get("method", "auto")
        if is_protected(path):
            protected_warned.append(path)
        if not os.path.exists(path):
            results.append({"path": path, "size": size, "success": True, "method": "already_gone"})
            already_gone_count += 1
            continue
        if method == "trash" or (method == "auto" and use_trash):
            trash_paths.append(path)
            trash_sizes[path] = size
        else:
            direct_items.append((path, size, method))

    # Trash in batches
    if trash_paths:
        trash_paths.sort(key=lambda p: trash_sizes.get(p, 0), reverse=True)
        for i in range(0, len(trash_paths), _TRASH_BATCH_SIZE):
            batch = trash_paths[i:i + _TRASH_BATCH_SIZE]
            for r in _send_to_trash(batch):
                if r["success"]:
                    success_count += 1
                    total_freed += trash_sizes.get(r["path"], 0)
                else:
                    fail_count += 1
                    errors.append(f"trash: {r['path']}: {r.get('error','?')}")
                results.append(r)

    # Direct in parallel
    if direct_items:
        direct_items.sort(key=lambda x: x[1], reverse=True)
        n = min(8, len(direct_items))
        with ThreadPoolExecutor(max_workers=n) as pool:
            futures = {
                pool.submit(_delete_one, path, size, method): (path, size)
                for path, size, method in direct_items
            }
            for f in as_completed(futures):
                try:
                    r = f.result()
                except Exception as e:
                    path, size = futures[f]
                    r = {"path": path, "size": size, "success": False, "error": str(e)}
                if r["success"]:
                    success_count += 1
                    total_freed += r.get("size", 0)
                else:
                    fail_count += 1
                    errors.append(f"del: {r['path']}: {r.get('error','?')}")
                results.append(r)

    _, after_free, _ = _get_disk_free(ref_path)
    actual_freed = after_free - before_free
    delta = actual_freed - total_freed

    # Feed learning loop: record what was cleaned
    try:
        from ..core.history import record_clean
        items_for_record = []
        for item in items:
            if isinstance(item, dict):
                items_for_record.append({"path": item.get("path", ""), "size": item.get("size", 0), "provider": item.get("provider", "unknown")})
            elif hasattr(item, "to_dict"):
                d = item.to_dict()
                items_for_record.append({"path": d.get("path", ""), "size": d.get("size", 0), "provider": getattr(item, "provider", "unknown")})
        if items_for_record:
            total = sum(i.get("size", 0) for i in items_for_record)
            record_clean(items_for_record, total, "delete", before_free, after_free)
    except Exception:
        pass
    
    return {
        "success_count": success_count, "fail_count": fail_count,
        "already_gone": already_gone_count,
        "total_freed": total_freed, "total_freed_human": format_size(total_freed),
        "errors": errors[:20], "results": results,
        "before_free": before_free, "after_free": after_free,
        "actual_freed": actual_freed, "actual_freed_human": format_size(max(actual_freed, 0)),
        "delta": delta,
        "delta_note": ("freed more than predicted" if delta > 0
                       else ("potential issue" if delta < 0 else "exact match")),
        "ellapsed_ms": (time.time() - start) * 1000,
        "protected_warned": protected_warned[:20] if protected_warned else None,
    }
