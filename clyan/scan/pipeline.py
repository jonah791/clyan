"""ScanPipeline — 三阶段扫描管线

分离"扫描器"（空间分析）和"垃圾扫描器"（可清理项发现）：

Phase 1 — 极速扫描 (<1s)
  ├ pulse 缓存 (0ms)
  └ disk summary depth=1 (6s)

Phase 2 — 全面垃圾检测 (8-15s)
  ├ all providers (detect_all, ~8s)
  ├ browser deep (~1s)
  ├ system temp (~0.5s)
  └ duplicates (>1GB groups, ~3s)

Phase 3 — 深度分析 (30s+)
  ├ space tree depth=3 (~15s)
  ├ large files (~5s)
  ├ node-waste (~3s)
  ├ packages (~2s)
  └ Winapp2 deep (~10s)
"""

import time, json
from typing import Optional


class ScanPipeline:
    """Progressive scan pipeline with three phases.
    
    Each phase returns more detail. Call in sequence: P1 → P2 → P3.
    Results accumulate — later phases don't re-scan what earlier ones did.
    """

    def __init__(self, path: str = ""):
        self.path = path
        self.results: dict[str, any] = {}
        self.errors: list[str] = []
        self._phase_times: dict[int, float] = {}

    # ── Phase 1: Fast overview ──

    def phase1(self) -> dict:
        """极速扫描: pulse + disk summary depth=1"""
        t0 = time.time()
        from ..reflex import check_pulse

        pulse = check_pulse(self.path)
        self.results["pulse"] = pulse
        self._phase_times[1] = time.time() - t0

        return self._report("Phase 1 (fast)", pulse)

    # ── Phase 2: Garbage detection ──

    def phase2_garbage(self) -> dict:
        """全面垃圾检测: providers + browser + system + duplicates"""
        t0 = time.time()

        from ..scan.providers import detect_all
        from ..scan.browser_deep import scan_browser_deep
        from ..scan.system import scan_system
        from ..scan.duplicates import DuplicateScanner

        # All providers
        results, errors = detect_all(self.path)
        self.errors.extend(errors)
        items = []
        for name, provider_items in results.items():
            for item in provider_items:
                d = item.to_dict()
                d["provider"] = name
                items.append(d)

        # Browser deep
        browser = scan_browser_deep()
        for item in browser.get("items", []):
            item["provider"] = "browser"
            items.append(item)

        # System
        sys_result = scan_system()
        for item in sys_result.get("items", []):
            item["provider"] = "system"
            items.append(item)

        # Duplicates (quick: only groups >1GB)
        dup_scanner = DuplicateScanner(self.path, min_group_size=1_000_000_000)
        dup_result = dup_scanner.scan()
        for item in dup_result.get("items", []):
            item["provider"] = "duplicates"
            items.append(item)

        self.results["garbage_items"] = items
        self._phase_times[2] = time.time() - t0
        gc_total = sum(i.get("size", 0) for i in items)
        gc_total_h = self._fmt(gc_total)

        return self._report(
            "Phase 2 (garbage)",
            {
                "items": items,
                "total_items": len(items),
                "total_size": gc_total,
                "total_size_human": gc_total_h,
            },
        )

    # ── Phase 3: Deep analysis ──

    def phase3_deep(self) -> dict:
        """深度分析: space tree + large files + node-waste + packages"""
        t0 = time.time()

        # Space tree
        from ..scan.space import SpaceScanner

        space = SpaceScanner(path=self.path, max_depth=3, top_n=50)
        space_result = space.scan().to_dict()
        self.results["space_tree"] = space_result

        # Large files
        from ..scan.large_files import LargeFileScanner

        lf = LargeFileScanner(self.path, min_size_mb=500)
        lf_result = lf.scan().to_dict()
        self.results["large_files"] = lf_result

        # Node waste
        from ..scan.node_waste import NodeWasteScanner

        nw = NodeWasteScanner(self.path)
        nw_result = nw.scan().to_dict()
        self.results["node_waste"] = nw_result

        # Packages
        from ..scan.packages import PackagesScanner

        pkgs = PackagesScanner()
        pkgs_result = pkgs.scan().to_dict()
        self.results["packages"] = pkgs_result

        self._phase_times[3] = time.time() - t0

        return self._report("Phase 3 (deep)", {
            "space": space_result,
            "large_files": lf_result,
            "node_waste": nw_result,
            "packages": pkgs_result,
        })

    # ── Smart progressive scan ──

    def scan_all(self, max_phase: int = 3) -> dict:
        """Run phases progressively up to max_phase."""
        final = {}
        if max_phase >= 1:
            final["phase1"] = self.phase1()
        if max_phase >= 2:
            final["phase2"] = self.phase2_garbage()
        if max_phase >= 3:
            final["phase3"] = self.phase3_deep()
        final["errors"] = self.errors
        final["phase_times"] = self._phase_times
        final["total_time"] = sum(self._phase_times.values())
        return final

    def scan_adaptive(self) -> dict:
        """Smart progressive: P1 → if low free → P2 → if large → P3."""
        p1 = self.phase1()
        free_gb = p1.get("data", {}).get("free_gb", 50)
        # If free < 20% total or < 30 GB, run phase 2
        if free_gb < 30:
            p2 = self.phase2_garbage()
            reclaimable = sum(i.get("size", 0) for i in p2.get("data", {}).get("items", []))
            # If > 10 GB reclaimable, run phase 3 for detailed breakdown
            if reclaimable > 10_000_000_000:
                p3 = self.phase3_deep()
                return {
                    "phases": [p1, p2, p3],
                    "errors": self.errors,
                    "phase_times": self._phase_times,
                    "total_time": sum(self._phase_times.values()),
                }
            return {"phases": [p1, p2], "errors": self.errors, "phase_times": self._phase_times}
        return {"phases": [p1], "errors": self.errors, "phase_times": self._phase_times}

    # ── Internal ──

    def _report(self, label: str, data: dict) -> dict:
        return {"label": label, "data": data, "ellapsed_ms": int(self._phase_times.get(len(self._phase_times)+1, 0)*1000)}

    @staticmethod
    def _fmt(size: int) -> str:
        if size > 1e9:   return f"{size/1e9:.2f} GB"
        if size > 1e6:   return f"{size/1e6:.1f} MB"
        if size > 1e3:   return f"{size/1e3:.0f} KB"
        return f"{size} B"
