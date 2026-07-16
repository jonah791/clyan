"""Inaccessibility tracker — count what we can't scan and why.

Usage:
    tracker = AccessTracker()
    # Use safe_walk with callback
    for dirpath, dirs, files in safe_walk(root, on_error=tracker.record):
        ...
    report = tracker.report()  # {"count": 5, "total_size_estimate": "...", "paths": [...]}
"""
import os
import time


class AccessTracker:
    """Track directories and files that couldn't be accessed during scanning."""

    def __init__(self):
        self.errors: list[dict] = []
        self._start = time.time()

    def record(self, path: str, error: str = "permission denied") -> None:
        """Record an inaccessible path."""
        # Deduplicate by path prefix
        for e in self.errors:
            if e["path"] == path or (e["path"] in path and len(e["path"]) > 10):
                return
        self.errors.append({
            "path": path,
            "error": error,
            "time": time.time() - self._start,
        })
        # Keep only last 50 to avoid memory issues
        if len(self.errors) > 50:
            self.errors = self.errors[-50:]

    def report(self, total_used: int = 0) -> dict:
        """Build a structured report of inaccessible paths."""
        if not self.errors:
            return {"accessible": True, "count": 0, "note": "no access issues"}

        # Group by parent directory
        parents: dict[str, int] = {}
        for e in self.errors:
            parent = os.path.dirname(e["path"])
            parents[parent] = parents.get(parent, 0) + 1

        top_parents = sorted(parents.items(), key=lambda x: -x[1])[:5]

        return {
            "accessible": False,
            "count": len(self.errors),
            "note": f"{len(self.errors)} paths were not accessible during scan",
            "top_blocked_dirs": [{"path": p, "blocked_count": c} for p, c in top_parents],
            "likely_unaccounted_gb": round(total_used * 0.05, 1) if total_used > 0 else 0,
        }

    def merge(self, other: "AccessTracker") -> None:
        """Merge another tracker's errors into this one."""
        for e in other.errors:
            self.record(e["path"], e["error"])
