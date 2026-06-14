import sys
import json
import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from .scan.space import SpaceScanner
from .scan.dev_garbage import DevGarbageScanner
from .scan.browser_cache import BrowserCacheScanner
from .scan.system import SystemScanner
from .scan.duplicates import DuplicateScanner
from .clean.preview import generate_preview
from .clean.execute import delete_items
from .core.history import get_history, get_operation


server = Server("clyan", version="0.1.0")


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
                "required": [],
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
                        "description": "List of items to preview. Each has path, size, type.",
                    },
                },
                "required": ["items"],
            },
        ),
        Tool(
            name="clean_execute",
            description="Execute deletion. Items go to recycle bin by default. Use --fast for direct deletion of large items.",
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
                    "fast": {"type": "boolean", "description": "Use direct deletion (skip recycle bin) for large items"},
                },
                "required": ["items"],
            },
        ),
        Tool(
            name="history",
            description="View cleanup history. Pass op_id to inspect a specific operation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "op_id": {"type": "number", "description": "Operation ID to inspect (optional)"},
                    "limit": {"type": "number", "description": "Max entries (default 20)"},
                },
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
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
            return [TextContent(type="text", text=json.dumps(results, ensure_ascii=False, indent=2))]

        elif name == "scan_dev_garbage":
            path = arguments.get("path", "C:\\")
            min_size_mb = arguments.get("min_size_mb", 0)
            s = DevGarbageScanner(root=path)
            data = s.scan().to_dict()
            if min_size_mb:
                mb = min_size_mb * 1024 * 1024
                data["items"] = [i for i in data["items"] if i["size"] >= mb]
                data["item_count"] = len(data["items"])
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

        elif name == "scan_browsers":
            s = BrowserCacheScanner()
            data = s.scan().to_dict()
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

        elif name == "scan_system":
            s = SystemScanner()
            data = s.scan().to_dict()
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

        elif name == "scan_duplicates":
            path = arguments.get("path", "C:\\")
            s = DuplicateScanner(path=path)
            data = s.scan().to_dict()
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

        elif name == "clean_preview":
            items = arguments.get("items", [])
            preview = generate_preview(items)
            return [TextContent(type="text", text=json.dumps(preview, ensure_ascii=False, indent=2))]

        elif name == "clean_execute":
            items = arguments.get("items", [])
            fast = arguments.get("fast", False)
            result = delete_items(items, fast=fast)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "history":
            op_id = arguments.get("op_id")
            limit = arguments.get("limit", 20)
            if op_id:
                data = get_operation(op_id)
            else:
                data = {"operations": get_history(limit=limit)}
            return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"unknown tool: {name}"}))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    anyio.run(main)
