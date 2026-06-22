import argparse
import json
import sys
import os

from .scan.space import SpaceScanner
from .scan.dev_garbage import DevGarbageScanner
from .scan.browser_cache import BrowserCacheScanner
from .scan.system import SystemScanner
from .scan.duplicates import DuplicateScanner
from .scan.packages import PackagesScanner
from .clean.preview import generate_preview
from .clean.execute import delete_items
from .core.history import get_history, get_operation, mark_undone
from .core.report import summarize_scan_results
from .utils.size import parse_size


def _out(data: dict):
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def cmd_scan_space(args):
    s = SpaceScanner(
        path=args.path,
        max_depth=args.depth,
        min_size=parse_size(args.min_size) if args.min_size else 0,
        top_n=args.top,
    )
    result = s.scan()
    _out(result.to_dict())


def cmd_scan_dev(args):
    s = DevGarbageScanner(root=args.path)
    result = s.scan()
    d = result.to_dict()
    if args.min_size_mb:
        min_bytes = args.min_size_mb * 1024 * 1024
        d["items"] = [i for i in d["items"] if i["size"] >= min_bytes]
        d["item_count"] = len(d["items"])
        d["total_size"] = sum(i["size"] for i in d["items"])
        d["total_size_human"] = _fmt(d["total_size"])
    if args.json_mode:
        sys.stdout.write(json.dumps(d["items"], ensure_ascii=False) + "\n")
    else:
        _out(d)


def _fmt(size: int) -> str:
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    v = float(size)
    while v >= 1024 and idx < len(suffixes) - 1:
        v /= 1024
        idx += 1
    return f"{v:.2f} {suffixes[idx]}"


def cmd_scan_browsers(args):
    s = BrowserCacheScanner()
    result = s.scan()
    _out(result.to_dict())


def cmd_scan_system(args):
    s = SystemScanner()
    result = s.scan()
    _out(result.to_dict())


def cmd_scan_duplicates(args):
    s = DuplicateScanner(path=args.path)
    result = s.scan()
    _out(result.to_dict())


def cmd_mcp(args):
    try:
        from .mcp_server import main as mcp_main
        import anyio
        anyio.run(mcp_main)
    except ImportError as e:
        _out({"error": f"MCP dependencies not available: {e}"})


def cmd_scan_packages(args):
    s = PackagesScanner()
    result = s.scan()
    d = result.to_dict()
    _out(d)


def cmd_scan_quick(args):
    results = {}

    s1 = SpaceScanner(path=args.path, max_depth=2, top_n=30)
    results["space"] = s1.scan().to_dict()

    s2 = DevGarbageScanner(root=args.path)
    results["dev_garbage"] = s2.scan().to_dict()

    s3 = BrowserCacheScanner()
    results["browsers"] = s3.scan().to_dict()

    s4 = SystemScanner()
    results["system"] = s4.scan().to_dict()

    summary = summarize_scan_results(results)

    if args.top and args.top > 0:
        all_items = []
        for name, data in results.items():
            for item in data.get("items", []):
                all_items.append({**item, "_category": name})
        all_items.sort(key=lambda x: x.get("size", 0), reverse=True)
        summary["top_items"] = all_items[:args.top]

    _out(summary)


def _filter_by_safety(items: list[dict], level: str) -> list[dict]:
    allowed = {"safe", "caution", "unsafe"}
    level = level.lower()
    if level not in allowed:
        return items
    levels = {"safe": 0, "caution": 1, "unsafe": 2}
    threshold = levels[level]
    return [i for i in items if levels.get(i.get("safety", "unsafe"), 2) >= threshold]


def cmd_clean(args):
    if args.items:
        if os.path.isfile(args.items):
            with open(args.items, "r", encoding="utf-8-sig") as f:
                items = json.load(f)
        else:
            items = json.loads(args.items)
    elif args.stdin:
        raw = sys.stdin.buffer.read().decode("utf-8-sig")
        items = json.loads(raw)
    else:
        _out({"error": "provide --items or --stdin"})
        return

    if not isinstance(items, list):
        items = items.get("items", items.get("valid_items", []))

    if args.safety:
        items = _filter_by_safety(items, args.safety)
        if not items:
            _out({"error": f"no items match safety level: {args.safety}"})
            return

    if args.dry_run:
        preview = generate_preview(items)
        _out(preview)
        return

    res = delete_items(items, use_trash=not args.permanent, fast=args.fast)
    _out(res)


def cmd_history(args):
    if args.id:
        op = get_operation(args.id)
        if op:
            op["items"] = json.loads(op["items_json"])
            _out(op)
        else:
            _out({"error": f"operation {args.id} not found"})
    else:
        rows = get_history(limit=args.limit)
        _out({"operations": rows})


def cmd_undo(args):
    ok = mark_undone(args.id)
    _out({"operation_id": args.id, "undone": ok})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clyan", description="AI-driven disk cleaner")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("scan", help="scan for cleanable items")
    sp_sub = sp.add_subparsers(dest="scan_type")

    sp_space = sp_sub.add_parser("space", help="analyze directory space usage")
    sp_space.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."))
    sp_space.add_argument("--depth", type=int, default=2)
    sp_space.add_argument("--min-size", default="0")
    sp_space.add_argument("--top", type=int, default=50)

    sp_dev = sp_sub.add_parser("dev-garbage", help="find developer cache garbage")
    sp_dev.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."))
    sp_dev.add_argument("--min-size-mb", type=int, default=0, help="only show items >= this many MB")
    sp_dev.add_argument("--json", dest="json_mode", action="store_true",
                        help="output raw items array (pipeable to clyan clean --stdin)")

    sp_browsers = sp_sub.add_parser("browsers", help="find browser caches")

    sp_sys = sp_sub.add_parser("system", help="find system temp files")

    sp_dup = sp_sub.add_parser("duplicates", help="find duplicate files by size+hash")
    sp_dup.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."))

    sp_pkgs = sp_sub.add_parser("packages", help="scan installed package environments (conda, scoop, cargo, go, npm)")
    sp_pkgs.add_argument("--json", dest="json_mode", action="store_true",
                         help="output raw items array (pipeable to clyan clean --stdin)")

    sp_quick = sp_sub.add_parser("quick", help="run all scans")
    sp_quick.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."))
    sp_quick.add_argument("--top", type=int, default=0, help="only show top N biggest items across all scans")

    cp = sub.add_parser("clean", help="preview or execute cleanup")
    cp.add_argument("--items", help="path to JSON file or JSON string with items")
    cp.add_argument("--stdin", action="store_true", help="read items JSON from stdin")
    cp.add_argument("--dry-run", action="store_true", help="preview only, no delete")
    cp.add_argument("--permanent", action="store_true", help="skip trash, permanent delete")
    cp.add_argument("--fast", action="store_true", help="direct delete for large items (default: recycle bin)")
    cp.add_argument("--safety", choices=["safe", "caution", "unsafe"],
                    help="minimum safety level (default: all). safe < caution < unsafe")

    hp = sub.add_parser("history", help="view cleanup history")
    hp.add_argument("--id", type=int, help="operation ID to inspect")
    hp.add_argument("--limit", type=int, default=20)

    up = sub.add_parser("undo", help="undo a cleanup operation")
    up.add_argument("id", type=int, help="operation ID to undo")

    mp = sub.add_parser("mcp", help="start MCP server for AI tool calls")

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "scan":
        dispatch = {
            "space": cmd_scan_space,
            "dev-garbage": cmd_scan_dev,
            "browsers": cmd_scan_browsers,
            "system": cmd_scan_system,
            "duplicates": cmd_scan_duplicates,
            "packages": cmd_scan_packages,
            "quick": cmd_scan_quick,
        }
        fn = dispatch.get(args.scan_type)
        if fn:
            fn(args)
        else:
            parser.print_help()
    elif args.command == "clean":
        cmd_clean(args)
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "undo":
        cmd_undo(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
