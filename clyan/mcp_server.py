"""Clyan MCP server — AI agent interface for disk cleaning.

7 tools, optimized for autonomous AI consumption.
"""
import sys, json, os, anyio, uuid
from typing import Any
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource

from .scan.providers import detect_all
from .scan.system import SystemScanner
from .scan.browser_deep import scan_browser_deep
from .scan.space import SpaceScanner
from .scan.disk_summary import scan_disk as scan_disk_fn
from .clean.preview import generate_preview
from .clean.execute import delete_items
from .utils.size import format_size
from .utils.scanner_base import _enrich
from .utils.confidence import compute_and_attach
from .core.history import get_history, get_operation, mark_undone

server = Server("clyan", version="2.1.0")
_proposals: dict[str, dict[str, Any]] = {}
import time
_PROPOSAL_TTL = 3600  # 1 hour


def _clean_stale_proposals():
    now = time.time()
    stale = [k for k, v in _proposals.items()
             if now - v.get("_ts", 0) > _PROPOSAL_TTL]
    for k in stale:
        _proposals.pop(k, None)


def _enrich_items(items: list[dict]) -> None:
    for item in items:
        try:
            _enrich(item)
            compute_and_attach(item)
        except Exception:
            item.setdefault("confidence", 0.0)
            item.setdefault("reason", "")


def _ok(data: dict) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]


# ─── Tool definitions ──────────────────────────────────

TOOLS = [
    Tool(
        name="scan",
        description="Universal scanner. Returns items[] with provider, safety (safe/caution/unsafe), confidence (0-1), recovery_cost (none/low/medium/high), ecosystem, would_break, would_affect. AI: scan -> analyze -> clean_propose.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Root path (default: user home)"},
                "include_duplicates": {"type": "boolean", "description": "Also scan for duplicate files (slower)"},
                "phase": {"type": "string", "enum": ["quick", "full"], "description": "quick (default) = providers only; full = all scanners"},
                "path": {"type": "string", "description": "Root path (default: user home)"},
            },
        },
    ),
    Tool(
        name="scan_disk",
        description="Disk space tree. Returns disk{total/used/free_human}, top_dirs[{size_human, cleanable, cleanable_pct}], gap_analysis, inaccessible[], root_files[]. Supports full (deeper) and clean (garbage classification).",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Drive or directory (default: C:\\)"},
                "depth": {"type": "number", "description": "Tree depth (default: 2)"},
            },
        },
    ),
    Tool(
        name="clean_propose",
        description="Prepare items for deletion. Returns action_id + impact. Items need path+size. Call clean_confirm to execute.",
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
    Tool(
        name="clean_confirm",
        description="Execute a prior clean_propose. Pass action_id from clean_propose. Returns {success_count, fail_count, total_freed_human, before_free, after_free}. Items go to recycle bin.",
        inputSchema={
            "type": "object",
            "properties": {
                "action_id": {"type": "string", "description": "The action_id from clean_propose"},
            },
            "required": ["action_id"],
        },
    ),
    Tool(
        name="system_health",
        description="One-shot disk health. Returns disk{total/used/free_human}, top_dirs[6], reclaimable, trend[5 snapshots], provider_feedback. First call to assess state.",
        inputSchema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Drive to check (default: C:\\)"},
            },
        },
    ),
    Tool(
        name="history",
        description="View cleanup operations. Pass op_id for detail or limit for recent list. Returns ops with {operation_id, action, freed_human, timestamp}. AI: history -> maybe undo.",
        inputSchema={
            "type": "object",
            "properties": {
                "op_id": {"type": "number", "description": "Operation ID to inspect"},
                "limit": {"type": "number", "description": "Max operations (default: 20)"},
            },
        },
    ),
    Tool(
        name="undo",
        description="Restore deleted items from recycle bin. Requires op_id from history. Returns {operation_id, undone}. Only recycle bin items. AI: history first -> undo.",
        inputSchema={
            "type": "object",
            "properties": {
                "op_id": {"type": "number", "description": "Operation ID to undo"},
            },
            "required": ["op_id"],
        },
    ),
]


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return TOOLS


@server.list_resources()
async def handle_list_resources():
    return [
        Resource(
            uri="disk://C:/health",
            name="C: Drive Health",
            description="Instant disk health snapshot",
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


# ─── Handlers ──────────────────────────────────────────

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        # ── scan ────────────────────────────────────
        if name == "scan":
            path = arguments.get("path", os.environ.get("USERPROFILE", "C:\\"))
            phase = arguments.get("phase", "quick")
            include_dups = arguments.get("include_duplicates", False)

            all_items: list[dict] = []

            # Providers (always)
            results, errors = detect_all(path)
            for prov_name, items in results.items():
                for item in items:
                    d = item.to_dict()
                    d["provider"] = prov_name
                    all_items.append(d)

            if phase == "full":
                # System
                try:
                    sys_result = SystemScanner().scan().to_dict()
                    for item in sys_result.get("items", []):
                        item["provider"] = "system"
                        all_items.append(item)
                except Exception as e:
                    errors.append(f"system: {e}")

                # Browsers
                try:
                    br_result = scan_browser_deep()
                    for item in br_result.get("items", []):
                        item["provider"] = "browser"
                        all_items.append(item)
                except Exception as e:
                    errors.append(f"browser: {e}")

                # Duplicates
                if include_dups:
                    try:
                        from .scan.duplicates import DuplicateScanner
                        dup_result = DuplicateScanner(path=path).scan().to_dict()
                        for item in dup_result.get("items", []):
                            item["provider"] = "duplicates"
                            all_items.append(item)
                    except Exception as e:
                        errors.append(f"duplicates: {e}")

            # Enrich all items with confidence/impact
            _enrich_items(all_items)

            return _ok({
                "items": all_items,
                "total_items": len(all_items),
                "total_size": sum(i.get("size", 0) for i in all_items),
                "total_size_human": format_size(sum(i.get("size", 0) for i in all_items)),
                "providers_used": len(set(i.get("provider", "?") for i in all_items)),
                "errors": errors[:5] if errors else [],
            })

        # ── scan_disk ────────────────────────────────
        elif name == "scan_disk":
            path = arguments.get("path", "C:\\")
            depth = arguments.get("depth", 2)
            full = arguments.get("full", False)
            clean = arguments.get("clean", False)
            from .scan.disk_summary import is_admin as _is_admin
            if full and not _is_admin():
                pass  # scan_disk will report inaccessible dirs
            result = scan_disk_fn(path=path, depth=depth, full=full, clean=clean)
            return _ok(result.to_dict())

        # ── clean_propose ────────────────────────────
        elif name == "clean_propose":
            items = arguments.get("items", [])
            _enrich_items(items)
            preview = generate_preview(items)

            action_id = str(uuid.uuid4())[:8]
            _proposals[action_id] = {"items": items, "_ts": time.time()}
            _clean_stale_proposals()

            return _ok({
                "action_id": action_id,
                "impact": {
                    "valid_count": len(preview.get("valid_items", [])),
                    "blocked_count": len(preview.get("blocked_items", [])),
                    "total_size": sum(i.get("size", 0) for i in preview.get("valid_items", [])),
                    "total_size_human": format_size(sum(i.get("size", 0) for i in preview.get("valid_items", []))),
                },
                "preview": preview,
            })

        # ── clean_confirm ────────────────────────────
        elif name == "clean_confirm":
            action_id = arguments.get("action_id", "")
            proposal = _proposals.pop(action_id, None)
            if proposal is None:
                return _ok({"error": f"action_id '{action_id}' not found or expired"})

            result = delete_items(proposal["items"])
            result["action_id"] = action_id
            return _ok(result)

        # ── system_health ────────────────────────────
        elif name == "system_health":
            path = arguments.get("path", "C:\\")
            from .scan.disk_summary import scan_disk
            from .core.history import get_disk_trend, get_provider_feedback

            disk_result = scan_disk(path, depth=1).to_dict()
            trend = get_disk_trend(path, limit=7)

            # Provider feedback (top providers)
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
                "disk": disk_result.get("disk", {}),
                "top_dirs": disk_result.get("top_dirs", [])[:6],
                "reclaimable": disk_result.get("reclaimable", {}),
                "trend": [{"date": s["timestamp"][:10], "free_human": format_size(s["free_size"])} for s in trend[-5:]] if trend else [],
                "provider_feedback": feedback,
            })

        # ── history ─────────────────────────────────
        elif name == "history":
            op_id = arguments.get("op_id")
            limit = arguments.get("limit", 20)
            if op_id:
                data = get_operation(op_id)
            else:
                data = {"operations": get_history(limit=limit)}
            return _ok(data)

        # ── undo ────────────────────────────────────
        elif name == "undo":
            op_id = arguments["op_id"]
            ok = mark_undone(op_id)
            return _ok({"operation_id": op_id, "undone": ok})

        else:
            return _ok({"error": f"unknown tool: {name}"})

    except Exception as e:
        return _ok({"error": str(e)})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

if __name__ == "__main__":
    anyio.run(main())
