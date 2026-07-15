import sys
import json
import os
import anyio
import uuid
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource

from .scan.space import SpaceScanner
from .scan.dev_garbage import DevGarbageScanner
from .scan.browser_cache import BrowserCacheScanner
from .scan.system import SystemScanner
from .scan.duplicates import DuplicateScanner
from .scan.packages import PackagesScanner
from .scan.disk_summary import scan_disk as scan_disk_fn
from .clean.preview import generate_preview
from .clean.execute import delete_items
from .utils.size import format_size
from .core.history import get_history, get_operation, mark_undone
from .utils.scanner_base import _enrich
from .utils.confidence import compute_and_attach


server = Server("clyan", version="0.12.0")

# ── In-memory store for two-phase clean proposals ──
_proposals: dict[str, dict[str, Any]] = {}


def _enrich_items(items: list[dict]) -> None:
    """Attach signals + confidence to every item in-place."""
    for item in items:
        try:
            _enrich(item)
            compute_and_attach(item)
        except Exception:
            item.setdefault("confidence", 0.0)
            item.setdefault("reason", "")


def _confidence_summary(items: list[dict]) -> dict:
    high = [i for i in items if i.get("confidence", 0) >= 0.8]
    mid = [i for i in items if 0.5 <= i.get("confidence", 0) < 0.8]
    low = [i for i in items if i.get("confidence", 0) < 0.5]
    return {
        "total_items": len(items),
        "high_confidence": len(high),
        "mid_confidence": len(mid),
        "low_confidence": len(low),
        "avg_confidence": round(
            sum(i.get("confidence", 0) for i in items) / max(len(items), 1), 2
        ),
    }


def _filter_strategy(items: list[dict], strategy: str) -> list[dict]:
    """Apply a named strategy to filter items."""
    if strategy == "safe":
        return [i for i in items if i.get("confidence", 0) >= 0.90
                and i.get("safety") == "safe"]
    elif strategy == "aged":
        return [i for i in items if i.get("age_days", 0) >= 90
                and i.get("safety") != "unsafe"]
    elif strategy == "orphan":
        return [i for i in items if i.get("tool_installed") is False
                or i.get("orphan") is True]
    elif strategy == "all":
        return [i for i in items if i.get("safety") != "unsafe"]
    return items


# ──────────────────────────────────────────────
# Tool registration
# ──────────────────────────────────────────────


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="scan_quick",
            description="Run all scanners on a path. Returns categorized summary of cleanable space.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root path to scan, e.g. C:\\"},
                },
            },
        ),
        Tool(
            name="scan_dev_garbage",
            description="Scan for developer cache garbage (node_modules, venvs, cargo, build artifacts, IDE caches, etc.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root path"},
                    "min_size_mb": {"type": "number", "description": "Only show items >= this many MB"},
                },
            },
        ),
        Tool(
            name="scan_browsers",
            description="Find browser caches (Chrome, Edge, Firefox)",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="scan_system",
            description="Find Windows system temp files and recycle bin size",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="scan_duplicates",
            description="Find duplicate files by size → hash comparison. 3-phase: size grouping, partial hash, full hash.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root path to scan for duplicates"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="scan_disk",
            description="Disk usage summary: total / used / free capacity, tree of largest directories, and reclaimable garbage estimate.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Drive or directory (default: C:\\)"},
                    "depth": {"type": "number", "description": "How many directory levels to show (default: 2)"},
                },
            },
        ),
        Tool(
            name="scan_packages",
            description="Scan installed package environments (conda, scoop, cargo, go, npm) for cleanup candidates.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="get_confidence_summary",
            description="Attach confidence scores + reasons to an items list and return a distribution summary. Useful after any scan to help decide what to delete.",
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of items from a scan. Each should have path, size, safety, provider.",
                    },
                },
                "required": ["items"],
            },
        ),
        Tool(
            name="clean_auto",
            description="One-shot autonomous cleanup: scan dev-garbage on path, score confidence, filter by strategy, execute. Returns clean result + confidence summary. Safer than manual clean_execute because it pre-filters.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root path to scan and clean"},
                    "strategy": {
                        "type": "string",
                        "description": "Filter strategy. 'safe' (confidence>=90%, SAFE only, default), 'aged' (unused ≥90d), 'orphan' (tool uninstalled), 'all' (skip only UNSAFE).",
                        "enum": ["safe", "aged", "orphan", "all"],
                    },
                    "min_confidence": {
                        "type": "number",
                        "description": "Override minimum confidence 0.0-1.0. Overrides strategy default.",
                    },
                    "use_trash": {
                        "type": "boolean",
                        "description": "Send to recycle bin (default true). Use false for permanent delete.",
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "Direct delete for large items (default false).",
                    },
                },
            },
        ),
        Tool(
            name="clean_deep",
            description="Full cleaning cycle: scans dev-garbage + system + browsers → scores → filters → executes → verifies freed space. Returns clean result + before/after disk comparison. Best single-call tool for autonomous agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Root path (default: user profile)"},
                    "strategy": {
                        "type": "string",
                        "enum": ["safe", "aged", "orphan", "all"],
                        "description": "Filter strategy (default: safe)",
                    },
                    "use_trash": {"type": "boolean", "description": "Send to recycle bin (default true)"},
                    "fast": {
                        "type": "boolean",
                        "description": "Direct delete for large items (default false).",
                    },
                },
            },
        ),
        Tool(
            name="clean_propose",
            description="Phase 1 of safe cleanup: receives items, enriches with confidence, returns an action_id + preview + confidence summary. Items are NOT deleted yet — call clean_confirm with the action_id to execute. Use this when you want to show the user what will happen before committing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of items to consider for deletion.",
                    },
                    "fast": {
                        "type": "boolean",
                        "description": "Use direct deletion (skip recycle bin) for large items.",
                    },
                },
                "required": ["items"],
            },
        ),
        Tool(
            name="clean_confirm",
            description="Phase 2 of safe cleanup: executes the items previously proposed via clean_propose. Takes an action_id returned by clean_propose. Returns the actual delete result.",
            inputSchema={
                "type": "object",
                "properties": {
                    "action_id": {
                        "type": "string",
                        "description": "The action_id returned by a prior clean_propose call.",
                    },
                },
                "required": ["action_id"],
            },
        ),
        Tool(
            name="clean_preview",
            description="Preview what would be deleted. Checks protected paths, returns valid + blocked items.",
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "size": {"type": "number"},
                                "type": {"type": "string"},
                            },
                        },
                        "description": "List of items to preview.",
                    },
                },
                "required": ["items"],
            },
        ),
        Tool(
            name="clean_execute",
            description="⚠ Execute deletion immediately. Items go to recycle bin by default. Use fast=true for direct deletion.",
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "size": {"type": "number"},
                                "type": {"type": "string"},
                            },
                        },
                    },
                    "fast": {"type": "boolean", "description": "Skip recycle bin for large items."},
                },
                "required": ["items"],
            },
        ),
        Tool(
            name="history",
            description="View cleanup history. Pass op_id to inspect one operation, or limit to control how many recent operations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "op_id": {"type": "number", "description": "Operation ID to inspect"},
                    "limit": {"type": "number", "description": "Max operations to return (default: 20)"},
                },
            },
        ),
        Tool(
            name="undo",
            description="Undo a cleanup operation by its operation ID (restores from recycle bin where possible).",
            inputSchema={
                "type": "object",
                "properties": {
                    "op_id": {"type": "number", "description": "Operation ID to undo"},
                },
                "required": ["op_id"],
            },
        ),
        Tool(
            name="system_health",
            description="Quick health check: disk usage + reclaimable summary + recent clean history + trend. Best first call for agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Drive to check (default: C:\\)"},
                },
            },
        ),
        Tool(
            name="get_provider_feedback",
            description="Return historical accuracy stats for a cache provider. Shows predicted vs actual freed for past clean operations.",
            inputSchema={
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "e.g. pip_cache, npm_cache, browser"},
                },
                "required": ["provider"],
            },
        ),
        Tool(
            name="clean_plan",
            description="Analyze items and return an optimized execution plan sorted by recovery_cost. Use when you have many items and want to minimize risk.",
            inputSchema={
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "List of items from a scan. Each should have path, size, provider.",
                    },
                },
                "required": ["items"],
            },
        ),
    ]


# ──────────────────────────────────────────────
# Tool handlers
# ──────────────────────────────────────────────


@server.call_tool()

@server.list_resources()
async def handle_list_resources():
    return [
        Resource(
            uri="disk://C:/health",
            name="C: Drive Health",
            description="Instant disk health: status, free space, safe reclaimable, trend",
            mimeType="application/json",
        ),
    ]


@server.read_resource()
async def handle_read_resource(uri: str):
    from .reflex import check_pulse
    if uri == "disk://C:/health":
        data = check_pulse("C:\\")
        return TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))
    raise ValueError(f"Unknown resource: {uri}")


async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        # ── check_disk_pulse ──
        if name == "check_disk_pulse":
            path = arguments.get("path", "C:\\")
            return _ok(check_pulse(path))

        # ── reclaim ──
        elif name == "reclaim":
            from .reclaim import reclaim as _reclaim, execute_phase as _execute_phase
            path = arguments.get("path", "C:\\")
            phase = arguments.get("phase", "")
            dry_run = arguments.get("dry_run", False)
            plan = _reclaim(path)
            if dry_run or not phase:
                return _ok(plan)
            result = _execute_phase(plan, phase)
            return _ok(result)

        # ── auto_clear_safe ──
        elif name == "auto_clear_safe":
            path = arguments.get("path", "C:\\")
            target_gb = arguments.get("target_gb", 0)
            return _ok(auto_clear_safe(path=path, target_gb=target_gb))

        # ── scan_quick ──
        if name == "scan_quick":
            path = arguments.get("path", "C:\\")
            results = {}
            for scanner_cls, key in [
                (lambda: SpaceScanner(path=path, max_depth=2, top_n=30), "space"),
                (lambda: DevGarbageScanner(root=path), "dev_garbage"),
                (lambda: BrowserCacheScanner(), "browsers"),
                (lambda: SystemScanner(), "system"),
            ]:
                try:
                    s = scanner_cls()
                    data = s.scan().to_dict()
                    results[key] = data
                except Exception as e:
                    results[key] = {"error": str(e)}
            return _ok(results)

        # ── scan_dev_garbage ──
        elif name == "scan_dev_garbage":
            path = arguments.get("path", "C:\\")
            min_size_mb = arguments.get("min_size_mb", 0)
            s = DevGarbageScanner(root=path)
            data = s.scan().to_dict()
            if min_size_mb:
                mb = min_size_mb * 1024 * 1024
                data["items"] = [i for i in data["items"] if i["size"] >= mb]
                data["item_count"] = len(data["items"])
            return _ok(data)

        # ── scan_browsers ──
        elif name == "scan_browsers":
            s = BrowserCacheScanner()
            return _ok(s.scan().to_dict())

        # ── scan_system ──
        elif name == "scan_system":
            s = SystemScanner()
            return _ok(s.scan().to_dict())

        # ── scan_duplicates ──
        elif name == "scan_duplicates":
            path = arguments.get("path", "C:\\")
            s = DuplicateScanner(path=path)
            return _ok(s.scan().to_dict())

        # ── scan_disk ──
        elif name == "scan_disk":
            path = arguments.get("path", "C:\\")
            depth = arguments.get("depth", 2)
            result = scan_disk_fn(path=path, depth=depth)
            return _ok(result.to_dict())

        # ── scan_packages ──
        elif name == "scan_packages":
            s = PackagesScanner()
            return _ok(s.scan().to_dict())

        # ── get_confidence_summary ──
        elif name == "get_confidence_summary":
            items = arguments.get("items", [])
            _enrich_items(items)
            return _ok({
                "items": items,
                "confidence_summary": _confidence_summary(items),
            })

        # ── clean_auto ──
        elif name == "clean_auto":
            path = arguments.get("path", os.environ.get("USERPROFILE", "C:\\"))
            strategy = arguments.get("strategy", "safe")
            min_confidence = arguments.get("min_confidence")
            use_trash = arguments.get("use_trash", True)

            # 1. Scan
            s = DevGarbageScanner(root=path)
            data = s.scan().to_dict()
            items = data.get("items", [])

            # 2. Enrich with confidence
            _enrich_items(items)

            # 3. Filter by strategy
            items = _filter_strategy(items, strategy)

            if min_confidence is not None:
                items = [i for i in items if i.get("confidence", 0) >= min_confidence]

            if not items:
                return _ok({"message": "No items match the filter criteria.", "deleted": 0})

            # 4. Execute
            fast = arguments.get("fast", False)
            result = delete_items(items, use_trash=use_trash, fast=fast)
            result["confidence_summary"] = _confidence_summary(items)
            return _ok(result)

        # ── clean_deep — full autonomous cycle ──
        elif name == "clean_deep":
            path = arguments.get("path", os.environ.get("USERPROFILE", "C:\\"))
            strategy = arguments.get("strategy", "safe")
            use_trash = arguments.get("use_trash", True)
            fast = arguments.get("fast", False)

            # 1. Run all scanners
            all_items: list[dict] = []
            for scanner_cls in [
                lambda: DevGarbageScanner(root=path),
                lambda: SystemScanner(),
                lambda: BrowserCacheScanner(),
            ]:
                try:
                    s = scanner_cls()
                    items = s.scan().to_dict().get("items", [])
                    all_items.extend(items)
                except Exception:
                    pass

            if not all_items:
                return _ok({"message": "No items found to clean.", "deleted": 0})

            # 2. Enrich with confidence
            _enrich_items(all_items)

            # 3. Filter by strategy
            items = _filter_strategy(all_items, strategy)

            if not items:
                return _ok({"message": f"No items match strategy '{strategy}'.", "deleted": 0})

            # 4. Execute
            result = delete_items(items, use_trash=use_trash, fast=fast)
            result["confidence_summary"] = _confidence_summary(items)

            # 5. Verify — get actual freed space
            from .clean.execute import _get_disk_free
            _, after_free, _ = _get_disk_free(path)
            before_free = result.get("before_free", 0)
            result["actual_freed"] = after_free - before_free
            result["actual_freed_human"] = format_size(max(after_free - before_free, 0))

            return _ok(result)

        # ── clean_propose (phase 1/2) ──
        elif name == "clean_propose":
            items = arguments.get("items", [])
            fast = arguments.get("fast", False)

            # Enrich + preview
            _enrich_items(items)
            preview = generate_preview(items)
            impact = {
                "valid_count": len(preview.get("valid_items", [])),
                "blocked_count": len(preview.get("blocked_items", [])),
                "total_size": sum(i.get("size", 0) for i in preview.get("valid_items", [])),
                "confidence_summary": _confidence_summary(items),
            }

            action_id = str(uuid.uuid4())[:8]
            _proposals[action_id] = {
                "items": items,
                "fast": fast,
            }

            return _ok({
                "action_id": action_id,
                "impact": impact,
                "preview": preview,
            })

        # ── clean_confirm (phase 2/2) ──
        elif name == "clean_confirm":
            action_id = arguments.get("action_id", "")
            proposal = _proposals.pop(action_id, None)
            if proposal is None:
                return _ok({"error": f"action_id '{action_id}' not found or already expired."})

            items = proposal["items"]
            fast = proposal["fast"]
            result = delete_items(items, fast=fast)
            result["action_id"] = action_id
            return _ok(result)

        # ── clean_preview ──
        elif name == "clean_preview":
            items = arguments.get("items", [])
            preview = generate_preview(items)
            return _ok(preview)

        # ── clean_execute ──
        elif name == "clean_execute":
            items = arguments.get("items", [])
            fast = arguments.get("fast", False)
            result = delete_items(items, fast=fast)
            return _ok(result)

        # ── history ──
        elif name == "history":
            op_id = arguments.get("op_id")
            limit = arguments.get("limit", 20)
            if op_id:
                data = get_operation(op_id)
            else:
                data = {"operations": get_history(limit=limit)}
            return _ok(data)

        # ── undo ──
        elif name == "undo":
            op_id = arguments["op_id"]
            ok = mark_undone(op_id)
            return _ok({"operation_id": op_id, "undone": ok})

        # ── system_health ──
        elif name == "system_health":
            path = arguments.get("path", "C:\\")
            from .scan.disk_summary import scan_disk
            from .core.history import get_disk_trend, get_provider_feedback
            disk_result = scan_disk(path, depth=1)
            disk_data = disk_result.to_dict()
            trend = get_disk_trend(path, limit=7)
            # Simple feedback: get top providers
            feedback = {}
            for p in ["npm_cache", "pip_cache", "browser", "system"]:
                try:
                    fb = get_provider_feedback(p, limit=3)
                    if fb:
                        feedback[p] = {
                            "ops": len(fb),
                            "avg_accuracy": round(sum(f["accuracy_ratio"] for f in fb) / len(fb), 2),
                        }
                except Exception:
                    pass
            return _ok({
                "disk": disk_data.get("disk", {}),
                "top_dirs": disk_data.get("top_dirs", [])[:6],
                "reclaimable": disk_data.get("reclaimable", {}),
                "trend": [{"date": s["timestamp"][:10], "free_human": format_size(s["free_size"])} for s in trend[-5:]] if trend else [],
                "provider_feedback": feedback,
            })

        # ── get_provider_feedback ──
        elif name == "get_provider_feedback":
            provider = arguments["provider"]
            from .core.history import get_provider_feedback as _gpf
            data = _gpf(provider, limit=10)
            return _ok({
                "provider": provider,
                "history": data,
                "summary": {
                    "total_ops": len(data),
                    "avg_accuracy": round(sum(f["accuracy_ratio"] for f in data) / max(len(data), 1), 2),
                    "total_predicted": sum(f["predicted_size"] for f in data),
                    "total_actual": sum(f["actual_freed"] for f in data),
                } if data else None,
            })

        # ── clean_plan ──
        elif name == "clean_plan":
            items = arguments.get("items", [])
            if not items:
                return _ok({"error": "No items provided", "plan": []})
            from .utils.confidence import REBUILD_HIGH, REBUILD_LOW, REBUILD_NONE
            _enrich_items(items)
            cost_order = {REBUILD_NONE: 0, "low": 1, REBUILD_LOW: 1, "medium": 2, REBUILD_HIGH: 3, "high": 3, "unknown": 4}
            sorted_items = sorted(
                items,
                key=lambda i: (cost_order.get(i.get("recovery_cost", "unknown"), 99), -i.get("size", 0))
            )
            by_cost: dict[str, list[dict]] = {}
            for i in sorted_items:
                c = i.get("recovery_cost", "unknown")
                by_cost.setdefault(c, []).append(i)
            phases = []
            for cost in [REBUILD_NONE, "low", "medium", "high", "unknown"]:
                if cost in by_cost:
                    phase_items = by_cost[cost]
                    phases.append({
                        "cost": cost,
                        "count": len(phase_items),
                        "total_size": sum(p.get("size", 0) for p in phase_items),
                        "total_size_human": format_size(sum(p.get("size", 0) for p in phase_items)),
                    })
            return _ok({
                "total_items": len(items),
                "total_size": sum(i.get("size", 0) for i in items),
                "total_size_human": format_size(sum(i.get("size", 0) for i in items)),
                "phases": phases,
                "recommendation": "Execute phases in order: start with 'none' cost items, verify, then proceed to higher cost items.",
                "plan": sorted_items,
            })

        else:
            return _ok({"error": f"unknown tool: {name}"})

    except Exception as e:
        return _ok({"error": str(e)})


def _ok(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    anyio.run(main)
