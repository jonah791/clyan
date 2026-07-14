import os
import json
from ..core.config import is_protected
from ..utils.size import format_size


def generate_preview(items: list[dict]) -> dict:
    validated = []
    blocked = []
    total = 0

    for item in items:
        raw_path = item.get("path", "")
        size = item.get("size", 0)
        # Resolve symlinks/junctions so is_protected sees the real path
        try:
            path = os.path.realpath(raw_path)
        except Exception:
            path = os.path.normpath(raw_path)
        if is_protected(path):
            blocked.append({
                "path": raw_path, "size": size,
                "reason": "protected system path",
            })
            continue
        if not os.path.exists(path):
            blocked.append({
                "path": raw_path, "size": size,
                "reason": "path does not exist",
            })
            continue
        validated.append({
            "path": path,
            "size": size,
            "size_human": format_size(size),
            "type": item.get("type", "unknown"),
        })
        total += size

    return {
        "valid_count": len(validated),
        "valid_items": validated,
        "blocked_count": len(blocked),
        "blocked_items": blocked,
        "total_size": total,
        "total_size_human": format_size(total),
    }
