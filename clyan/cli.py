import argparse
import json
import sys
import os

_VERBOSE = False
CLYAN_CONFIG = {"verbose": False, "json": False}


def _out(data: dict) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    if _VERBOSE:
        errors = data.get("errors", [])
        if errors:
            for err in errors:
                print(f"  [!] {err}", file=sys.stderr)


from .scan.space import SpaceScanner
from .scan.dev_garbage import DevGarbageScanner
from .scan.disk_summary import is_admin


def _elevate_and_rerun() -> None:
    """Re-launch current command as administrator."""
    import subprocess, ctypes
    import subprocess
    cmd = [sys.executable, "-m", "clyan"] + sys.argv[1:]
    # Remove --elevate to avoid loop
    while "--elevate" in cmd:
        cmd.remove("--elevate")
    print("Requesting administrator privileges...", file=sys.stderr)
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable,
        subprocess.list2cmdline(cmd[1:]),
        None, 1
    )
    sys.exit(0)
from .scan.browser_cache import BrowserCacheScanner
from .scan.system import SystemScanner
from .scan.duplicates import DuplicateScanner
from .scan.packages import PackagesScanner
from .scan.disk_summary import scan_disk
from .clean.preview import generate_preview
from .clean.execute import delete_items
from .core.history import get_history, get_operation, mark_undone
from .core.report import summarize_scan_results
from .utils.size import parse_size
from .utils.size import format_size
from .utils.dirtree import reset_dir_total_cache


def cmd_scan_space(args: argparse.Namespace) -> None:
    s = SpaceScanner(
        path=args.path,
        max_depth=args.depth,
        min_size=parse_size(args.min_size) if args.min_size else 0,
        top_n=args.top,
    )
    result = s.scan()
    _out(result.to_dict())


def cmd_scan_dev(args: argparse.Namespace) -> None:
    s = DevGarbageScanner(root=args.path)
    result = s.scan()
    d = result.to_dict()
    if args.min_size_mb:
        min_bytes = args.min_size_mb * 1024 * 1024
        d["items"] = [i for i in d["items"] if i["size"] >= min_bytes]
        d["item_count"] = len(d["items"])
        d["total_size"] = sum(i["size"] for i in d["items"])
        d["total_size_human"] = format_size(d["total_size"])
    if args.json_mode:
        sys.stdout.write(json.dumps(d["items"], ensure_ascii=False) + "\n")
    else:
        _out(d)

    if args.explain:
        d["confidence_summary"] = _summarize_confidence(d.get("items", []))




def cmd_scan_browsers(args: argparse.Namespace) -> None:
    s = BrowserCacheScanner()
    result = s.scan()
    _out(result.to_dict())


def cmd_scan_system(args: argparse.Namespace) -> None:
    s = SystemScanner()
    result = s.scan()
    _out(result.to_dict())


def cmd_scan_duplicates(args: argparse.Namespace) -> None:
    s = DuplicateScanner(path=args.path)
    result = s.scan()
    d = result.to_dict()
    if getattr(args, "json_mode", False):
        # Flatten duplicate groups into individual deletable items
        flat = []
        for group in d.get("items", []):
            for dup in group.get("duplicates", []):
                flat.append({
                    "path": dup["path"],
                    "size": dup["size"],
                    "size_human": format_size(dup["size"]),
                    "provider": "duplicates",
                    "safety": "safe",
                    "label": f"Duplicate: {os.path.basename(dup['path'])}",
                    "extra": {"keep_path": group.get("keep", "")},
                })
        sys.stdout.write(json.dumps(flat, ensure_ascii=False) + "\n")
    else:
        _out(d)


def cmd_mcp(args: argparse.Namespace) -> None:
    try:
        from .mcp_server import main as mcp_main
        import anyio
        anyio.run(mcp_main)
    except ImportError as e:
        _out({"error": f"MCP dependencies not available: {e}"})


def cmd_scan_packages(args: argparse.Namespace) -> None:
    s = PackagesScanner()
    result = s.scan()
    d = result.to_dict()
    _out(d)


def cmd_scan_quick(args: argparse.Namespace) -> None:
    reset_dir_total_cache()
    results = {}

    results["space"] = SpaceScanner(path=args.path, max_depth=2, top_n=30).scan().to_dict()
    results["dev_garbage"] = DevGarbageScanner(root=args.path).scan().to_dict()
    results["browsers"] = BrowserCacheScanner().scan().to_dict()
    results["system"] = SystemScanner().scan().to_dict()

    summary = summarize_scan_results(results)

    if args.top and args.top > 0:
        all_items = []
        for name, data in results.items():
            for item in data.get("items", []):
                all_items.append({**item, "_category": name})
        all_items.sort(key=lambda x: x.get("size", 0), reverse=True)
        summary["top_items"] = all_items[:args.top]

    # Attach disk summary
    try:
        disk_result = scan_disk(args.path)
        disk_dict = disk_result.to_dict()
        extra = disk_dict.get("extra", {})
        if "disk" in extra:
            summary["disk"] = extra["disk"]
        if "reclaimable" in extra:
            summary["reclaimable"] = extra["reclaimable"]
    except Exception:
        pass

    _out(summary)


def cmd_scan_disk(args: argparse.Namespace) -> None:
    reset_dir_total_cache()
    depth = getattr(args, "depth", 2)
    full = getattr(args, "full", False)
    elevate = getattr(args, "elevate", False)
    
    # Request elevation if needed
    if elevate or (full and not is_admin()):
        _elevate_and_rerun()
        return
    
    result = scan_disk(args.path, depth=depth, full=full)
    d = result.to_dict()

    # Auto-record snapshot for trend tracking
    disk = d.get("disk", {})
    if disk.get("total"):
        from .core.history import record_disk_snapshot
        record_disk_snapshot(
            path=disk["path"],
            total=disk["total"],
            free=disk["free"],
            used=disk["used"],
        )

    # If --trend requested, attach history
    if getattr(args, "trend", False):
        from .core.history import get_disk_trend
        snapshots = get_disk_trend(disk.get("path", args.path), limit=14)
        if len(snapshots) >= 2:
            trends = []
            for i in range(1, len(snapshots)):
                prev, curr = snapshots[i - 1], snapshots[i]
                delta_free = curr["free_size"] - prev["free_size"]
                trends.append({
                    "date": curr["timestamp"][:10],
                    "used_pct": round(curr["used_size"] / max(curr["total_size"], 1) * 100, 1),
                    "free_gb": round(curr["free_size"] / 1e9, 1),
                    "delta_free_gb": round(delta_free / 1e9, 1),
                })
            d["trend"] = trends

    _out(d)


def _filter_by_safety(items: list[dict], level: str) -> list[dict]:
    allowed = {"safe", "caution", "unsafe"}
    level = level.lower()
    if level not in allowed:
        return items
    levels = {"safe": 0, "caution": 1, "unsafe": 2}
    threshold = levels[level]
    return [i for i in items if levels.get(i.get("safety", "unsafe"), 2) <= threshold]


def _ensure_confidence(items: list[dict]) -> None:
    """Enrich items with signals + confidence if missing."""
    from .utils.scanner_base import _enrich
    from .utils.confidence import compute_and_attach
    for item in items:
        _enrich(item)
        compute_and_attach(item)


def _summarize_confidence(items: list[dict]) -> dict:
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


def _cmd_clean_deep(args: argparse.Namespace) -> None:
    """Full autonomous cleaning cycle: scan → score → filter → execute → verify → report."""
    from .scan.dev_garbage import DevGarbageScanner
    from .scan.system import SystemScanner
    from .scan.browser_cache import BrowserCacheScanner
    from .clean.execute import delete_items, _get_disk_free
    from .scan.disk_summary import scan_disk

    root = getattr(args, "path", os.environ.get("USERPROFILE", "C:\\"))
    strategy = getattr(args, "strategy", "safe")
    yes_mode = getattr(args, "yes", False)

    print("🔍 Scanning for cleanable items...", file=sys.stderr)

    # Phase 1: Run all scanners
    all_items = []
    all_errors = []
    for scanner, label in [
        (DevGarbageScanner(root=root), "developer garbage"),
        (SystemScanner(), "system temp"),
        (BrowserCacheScanner(), "browser caches"),
    ]:
        try:
            r = scanner.scan()
            d = r.to_dict()
            items = d.get("items", [])
            all_items.extend(items)
            errs = d.get("errors", [])
            if errs:
                for e in errs:
                    all_errors.append(e)
            print(f"  {'✓' if not errs else '⚠'} {label}: {len(items)} items", file=sys.stderr)
        except Exception as e:
            all_errors.append(f"{label}: {e}")
            print(f"  ✗ {label}: {e}", file=sys.stderr)

    if not all_items:
        _out({"error": "no items found to clean"})
        return

    # Phase 2: Score with confidence
    _ensure_confidence(all_items)

    # Phase 3: Filter
    from .utils.confidence import REBUILD_NONE, REBUILD_LOW
    if strategy == "safe":
        filtered = [i for i in all_items if i.get("confidence", 0) >= 0.90
                    and i.get("safety") == "safe"]
    elif strategy == "aged":
        filtered = [i for i in all_items if i.get("age_days", 0) >= 90
                    and i.get("safety") != "unsafe"]
    elif strategy == "orphan":
        filtered = [i for i in all_items if i.get("tool_installed") is False
                    or i.get("orphan") is True]
    elif strategy == "all":
        filtered = [i for i in all_items if i.get("safety") != "unsafe"]
    else:
        filtered = all_items

    if not filtered:
        _out({"error": f"no items match strategy '{strategy}'"})
        return

    total_predicted = sum(i.get("size", 0) for i in filtered)
    cs = _summarize_confidence(filtered)

    # Phase 4: Show impact
    print(f"\n📊 Impact summary:", file=sys.stderr)
    print(f"  Items to delete: {len(filtered)}", file=sys.stderr)
    print(f"  Predicted freed: {format_size(total_predicted)}", file=sys.stderr)
    print(f"  Confidence: {cs['high_confidence']} high, {cs['mid_confidence']} mid, {cs['low_confidence']} low", file=sys.stderr)

    # Show top 10 items
    filtered.sort(key=lambda x: -x.get("size", 0))
    print(f"\n  Top items:", file=sys.stderr)
    for item in filtered[:10]:
        sz = format_size(item.get("size", 0))
        print(f"    {sz:>9s}  {item.get('label','') or item['path'][:50]}", file=sys.stderr)

    # Phase 5: Confirm
    if not yes_mode:
        try:
            resp = input("\nContinue? [Y/n]: ").strip().lower()
            if resp not in ("", "y", "yes"):
                _out({"message": "cancelled by user"})
                return
        except (EOFError, KeyboardInterrupt):
            _out({"message": "cancelled by user"})
            return

    # Phase 6: Execute
    print(f"\n🧹 Cleaning...", file=sys.stderr)
    res = delete_items(filtered, use_trash=not getattr(args, "permanent", False),
                       fast=getattr(args, "fast", False))

    # Phase 7: Verify — measure actual freed space
    ref_path = filtered[0].get("path", root) if filtered else root
    _, after_free, _ = _get_disk_free(ref_path)
    actual_freed = after_free - res.get("before_free", after_free)

    res["confidence_summary"] = cs
    res["actual_freed"] = actual_freed
    res["actual_freed_human"] = format_size(max(actual_freed, 0))
    res["total_predicted"] = total_predicted
    res["total_predicted_human"] = format_size(total_predicted)
    res["root"] = root
    res["strategy"] = strategy
    if all_errors:
        res["scanner_errors"] = all_errors

    # Also get disk summary after cleanup
    print(f"  Verifying disk space...", file=sys.stderr)
    try:
        disk_result = scan_disk(root, depth=1)
        disk_data = disk_result.to_dict()
        res["disk_after"] = disk_data.get("disk", {})
    except Exception:
        pass

    _out(res)


def _cmd_clean_dedupe(args: argparse.Namespace, strategy: str) -> None:
    """Deduplicate: scan for duplicates, apply strategy, delete extras."""
    from .scan.duplicates import DuplicateScanner
    print("🔍 Scanning for duplicates...", file=sys.stderr)
    s = DuplicateScanner(path=args.path or os.environ.get("USERPROFILE", "C:\\"))
    result = s.scan()
    d = result.to_dict()

    groups = d.get("items", [])
    if not groups:
        _out({"message": "No duplicate files found."})
        return

    total_savings = sum(g.get("savings", 0) for g in groups)
    total_files = sum(g.get("duplicate_count", 0) for g in groups)
    print(f"  Found {len(groups)} duplicate groups, {total_files} files, {format_size(total_savings)} reclaimable", file=sys.stderr)

    # Build items list: keep the chosen copy, delete the rest
    to_delete = []
    for group in groups:
        all_paths = [(group["keep"], True)]
        for dup in group.get("duplicates", []):
            all_paths.append((dup["path"], False))

        if strategy == "keep-newest":
            # Find newest by mtime, delete all others
            all_paths.sort(key=lambda x: os.path.getmtime(x[0]), reverse=True)
            for path, _ in all_paths[1:]:  # keep paths[0] (newest), delete rest
                sz = sum(d["size"] for d in group["duplicates"] if d["path"] == path)
                if sz == 0:
                    try: sz = os.path.getsize(path)
                    except: sz = 0
                to_delete.append({"path": path, "size": sz,
                                   "safety": "safe", "provider": "duplicates"})
        elif strategy == "keep-first":
            # Keep the first (keep = oldest), delete all in duplicates list
            for dup in group.get("duplicates", []):
                to_delete.append({"path": dup["path"], "size": dup["size"],
                                   "safety": "safe", "provider": "duplicates"})
        elif strategy == "keep-smallest":
            # Sort by file size, keep smallest, delete rest
            all_paths.sort(key=lambda x: os.path.getsize(x[0]))
            for path, _ in all_paths[1:]:
                sz = sum(d["size"] for d in group["duplicates"] if d["path"] == path)
                if sz == 0:
                    try: sz = os.path.getsize(path)
                    except: sz = 0
                to_delete.append({"path": path, "size": sz,
                                   "safety": "safe", "provider": "duplicates"})

    if not to_delete:
        _out({"message": "No files to delete after applying strategy."})
        return

    print(f"  Will delete {len(to_delete)} files, keep {len(groups)} originals", file=sys.stderr)

    # Preview or execute
    if getattr(args, "dry_run", False):
        preview = generate_preview(to_delete)
        _out(preview)
        return

    if not getattr(args, "yes", False):
        try:
            resp = input(f"Continue? [Y/n]: ").strip().lower()
            if resp not in ("", "y", "yes"):
                _out({"message": "cancelled by user"})
                return
        except (EOFError, KeyboardInterrupt):
            _out({"message": "cancelled by user"})
            return

    res = delete_items(to_delete, use_trash=not getattr(args, "permanent", False),
                       fast=getattr(args, "fast", False))
    _out(res)


def cmd_clean(args: argparse.Namespace) -> None:
    # --deep mode: full autonomous cleaning cycle
    if getattr(args, "deep", False):
        _cmd_clean_deep(args)
        return

    # --dedupe mode: scan duplicates, apply strategy, clean
    dedupe_strategy = getattr(args, "dedupe", None)
    if dedupe_strategy:
        _cmd_clean_dedupe(args, dedupe_strategy)
        return

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

    # Ensure confidence + signals on all items
    _ensure_confidence(items)

    # Apply auto-safe: confidence >= 0.90 AND safety == safe
    if args.auto_safe:
        items = [i for i in items if i.get("confidence", 0) >= 0.90 and i.get("safety") == "safe"]
        if not items:
            _out({"error": "no items pass auto-safe filter (confidence >= 0.90 & safety == safe)"})
            return

    if args.min_confidence is not None:
        threshold = args.min_confidence / 100.0
        items = [i for i in items if i.get("confidence", 0) >= threshold]
        if not items:
            _out({"error": f"no items match --min-confidence {args.min_confidence}"})
            return

    if args.safety:
        items = _filter_by_safety(items, args.safety)
        if not items:
            _out({"error": f"no items match safety level: {args.safety}"})
            return

    if args.dry_run:
        preview = generate_preview(items)
        if args.explain:
            preview["confidence_summary"] = _summarize_confidence(items)
            for item in preview.get("valid_items", []):
                for src in items:
                    if src.get("path") == item["path"]:
                        item["confidence"] = src.get("confidence", 0)
                        item["reason"] = src.get("reason", "")
                        break
        _out(preview)
        return

    res = delete_items(items, use_trash=not args.permanent, fast=args.fast)
    if args.explain:
        res["confidence_summary"] = _summarize_confidence(items)
        for item in res.get("results", []):
            for src in items:
                if src.get("path") == item.get("path"):
                    item["confidence"] = src.get("confidence", 0)
                    item["reason"] = src.get("reason", "")
                    break
    _out(res)


def cmd_history(args: argparse.Namespace) -> None:
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



def cmd_report(args: argparse.Namespace) -> None:
    """Generate AI-ready report of reclaimable space."""
    import time, json
    from .report import build_report
    from .utils.size import format_size

    t0 = time.time()
    path = os.path.abspath(args.path)

    # Run all scans
    print("Scanning " + path + "...", file=sys.stderr)
    from .scan.providers import detect_all
    results, errors = detect_all(path)
    from .scan.browser_deep import scan_browser_deep
    browser_result = scan_browser_deep()
    from .scan.system import SystemScanner
    sys_result = SystemScanner().scan().to_dict()

    # Collect all items into dicts
    all_items = []
    for name, items in results.items():
        for item in items:
            d = item.to_dict()
            d["provider"] = name
            all_items.append(d)
    for item in browser_result.get("items", []):
        item["provider"] = "browser"
        all_items.append(item)
    for item in sys_result.get("items", []):
        item["provider"] = "system"
        all_items.append(item)

    # Build report
    report = build_report(all_items, path)

    # Apply filters
    if args.cost:
        report["phases"] = [p for p in report["phases"] if p["cost"] == args.cost]
        report["items"] = [i for i in report["items"] if i.get("recovery_cost", "unknown") == args.cost]
    if args.ecosystem:
        report["phases"] = [p for p in report["phases"] if any(
            e["ecosystem"] == args.ecosystem for e in p.get("ecosystem_breakdown", []))]
        report["items"] = [i for i in report["items"] if i.get("ecosystem", "other") == args.ecosystem]
    if args.min_size_mb > 0:
        min_bytes = args.min_size_mb * 1000000
        report["items"] = [i for i in report["items"] if i.get("size", 0) >= min_bytes]
        report["total_items"] = len(report["items"])
        report["total_size"] = sum(i.get("size", 0) for i in report["items"])
        report["total_size_human"] = format_size(report["total_size"])

    report["scan_time_ms"] = int((time.time() - t0) * 1000)
    report["errors"] = errors

    # Human stderr output
    sep = "=" * 50
    print(sep, file=sys.stderr)
    print("  Clyan Report -- " + path, file=sys.stderr)
    print("  " + report["total_size_human"] + " reclaimable (" + str(report["total_items"]) + " items)", file=sys.stderr)
    print("  Scan: " + str(report["scan_time_ms"] / 1000) + "s", file=sys.stderr)
    print(sep, file=sys.stderr)
    for p in report["phases"]:
        icons = {"none": "GRO", "low": "YEL", "medium": "ORA", "high": "RED", "unknown": "BLK"}
        icon = icons.get(p["cost"], "???")
        eco = ", ".join([e["ecosystem"] + ": " + e["size_human"] for e in p.get("ecosystem_breakdown", [])])
        msg = "  " + icon + "  Phase " + p["cost"] + ": " + p["total_size_human"] + " (" + str(p["item_count"]) + " items)"
        if eco:
            msg += " -- " + eco
        print(msg, file=sys.stderr)
    print("  " + report["recommendation"], file=sys.stderr)

    # Full JSON to stdout
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors:
        print("WARNING: " + str(len(errors)) + " provider errors", file=sys.stderr)
        for e in errors[:5]:
            print("   " + str(e), file=sys.stderr)


def cmd_doctor(args: argparse.Namespace) -> None:
    """Clyan system diagnosis: health check for all layers."""
    import sys, os, json, time
    from clyan import __version__ as ver

    ok_count, fail_count = 0, 0
    checks = []

    def check(label, ok, detail=""):
        nonlocal ok_count, fail_count
        if ok: ok_count += 1
        else: fail_count += 1
        icon = "\u2705" if ok else "\u274c"
        line = f"  {icon} {label}"
        print(line)
        if detail and args.verbose:
            for d in detail.split("\n"):
                print(f"       {d}")

    print("\n=== Clyan System Diagnosis ===")
    print(f"  Version: {ver}")
    print(f"  Python: {sys.version.split()[0]}")
    print()

    # 1. Import sanity
    try:
        from clyan.scan.providers import get_registered_providers
        from clyan.reflex import check_pulse
        from clyan.core.history import _get_db
        from clyan.utils.impact import _IMPACT_DB, impact_for
        check("All core modules importable", True)
    except Exception as e:
        check("Core imports", False, str(e))
        return

    # 2. DB writable
    try:
        db_path = _get_db()
        writable = os.access(db_path, os.W_OK) if os.path.isfile(db_path) else os.access(os.path.dirname(db_path), os.W_OK)
        check(f"Database writable ({os.path.basename(db_path)})", writable)
    except Exception as e:
        check("Database", False, str(e))

    # 3. Pulse
    try:
        pulse = check_pulse("C:\\")
        free = pulse.get("free_gb", 0)
        status = pulse.get("status", "unknown")
        check(f"Disk pulse: {free} GB free ({status})", True)
    except Exception as e:
        check("Disk pulse", False, str(e))

    # 4. Provider count
    try:
        provs = get_registered_providers()
        check(f"Registered providers: {len(provs)}", len(provs) >= 50)
    except Exception as e:
        check("Providers", False, str(e))

    # 5. Impact coverage
    try:
        missing = [n for n in provs if n not in _IMPACT_DB]
        check(f"Impact entries: 0 missing", len(missing) == 0)
    except Exception as e:
        check("Impact entries", False, str(e))

    # 6. Tests
    try:
        import subprocess
        r = subprocess.run([sys.executable, "-m", "pytest", "clyan/tests/", "-q"], capture_output=True, text=True, timeout=30)
        last = r.stdout.strip().split("\n")[-1] if r.stdout else "?"
        check(f"Tests: {last}", r.returncode == 0)
    except Exception as e:
        check("Tests", False, str(e))

    # 7. Phase 1
    try:
        from clyan.scan.pipeline import ScanPipeline
        p1 = ScanPipeline("C:\\").phase1()
        free = p1.get("data", {}).get("free_gb", "?")
        cached = p1.get("data", {}).get("cached", False)
        check(f"Phase 1 scan: {free} GB free (cached={cached})", True)
    except Exception as e:
        check("Phase 1 scan", False, str(e))

    # 8. MCP server
    try:
        from clyan.mcp_server import server
        check("MCP server module loaded", True)
    except Exception as e:
        check("MCP server", False, str(e))

    print(f"\n  {ok_count}/{ok_count+fail_count} checks passed")
    if fail_count > 0:
        print(f"  WARNING: {fail_count} check(s) failed")
    print()


def cmd_benchmark(args: argparse.Namespace) -> None:
    """Benchmark all providers and show top timings."""
    from .scan.providers import benchmark_providers
    import json
    results = benchmark_providers(args.path)
    total = sum(r.get("time_s", 0) for r in results)
    print(json.dumps({"top_slowest": results, "total_time_s": round(total, 2)}, ensure_ascii=False, indent=2))


def cmd_undo(args: argparse.Namespace) -> None:
    ok = mark_undone(args.id)
    _out({"operation_id": args.id, "undone": ok})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="clyan", description="AI-driven disk cleaner")
    p.add_argument("--verbose", "-v", action="store_true", help="show detailed error information")
    p.add_argument("--json", "-j", action="store_true", help="pure JSON output (no human-readable messages)")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("scan", help="scan for cleanable items (default: progressive 3-phase)")
    sp.add_argument("--phase", type=int, choices=[1,2,3],
                    help="explicit phase: 1=fast <1s, 2=garbage 8s, 3=deep 30s+")
    sp.add_argument("--path", nargs="?", default="C:\\",
                    help="path to scan (default: C:\\)")
    sp_sub = sp.add_subparsers(dest="scan_type")
    sp_sub.required = False
    sp.set_defaults(scan_type=None)

    sp_space = sp_sub.add_parser("space", help="[legacy] analyze directory space usage")

    sp_space.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."))
    sp_space.add_argument("--depth", type=int, default=2)
    sp_space.add_argument("--min-size", default="0")
    sp_space.add_argument("--top", type=int, default=50)

    sp_dev = sp_sub.add_parser("dev-garbage", help="[legacy] find developer cache garbage")
    sp_dev.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."))
    sp_dev.add_argument("--min-size-mb", type=int, default=0,
                        help="only show items >= this many MB")
    sp_dev.add_argument("--explain", action="store_true",
                        help="show confidence scores and reasons")
    sp_dev.add_argument("--json", dest="json_mode", action="store_true",
                        help="output raw items array (pipeable to clyan clean --stdin)")

    sp_browsers = sp_sub.add_parser("browsers", help="[legacy] find browser caches")

    sp_sys = sp_sub.add_parser("system", help="[legacy] find system temp files")

    sp_dup = sp_sub.add_parser("duplicates", help="[legacy] find duplicate files")
    sp_dup.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."))
    sp_dup.add_argument("--json", dest="json_mode", action="store_true",
                        help="output raw items array (pipeable to clyan clean --stdin)")

    sp_pkgs = sp_sub.add_parser("packages",
                                help="[legacy] scan package environments (conda, scoop, cargo, go, npm)")
    sp_pkgs.add_argument("--json", dest="json_mode", action="store_true",
                         help="output raw items array (pipeable to clyan clean --stdin)")

    sp_quick = sp_sub.add_parser("quick", help="[legacy] run all scans")
    sp_quick.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."))
    sp_quick.add_argument("--top", type=int, default=0,
                          help="only show top N biggest items across all scans")

    sp_disk = sp_sub.add_parser("disk", help="[legacy] disk usage summary")
    sp_disk.add_argument("path", nargs="?", default="C:\\",
                         help="drive or directory path (default: C:\\")
    sp_disk.add_argument("--depth", type=int, default=2,
                         help="how many levels to show (default: 2)")
    sp_disk.add_argument("--trend", action="store_true",
                         help="show disk usage history (requires prior snapshots)")
    sp_disk.add_argument("--full", action="store_true",
                         help="single-pass full scan (covers more space, slower)")
    sp_disk.add_argument("--elevate", action="store_true",
                         help="re-launch as administrator for full access")

    sp_files = sp_sub.add_parser("files", help="[legacy] find largest files")
    sp_files.add_argument("path", nargs="?", default="C:\\",
                          help="root path (default: C:\\)")
    sp_files.add_argument("--min-size", type=int, default=50,
                          help="minimum file size in MB (default: 50)")
    sp_files.add_argument("--top", type=int, default=50,
                          help="number of largest files to show (default: 50)")
    sp_files.add_argument("--json", dest="json_mode", action="store_true",
                          help="output raw items array (pipeable to clyan clean --stdin)")

    sp_nw = sp_sub.add_parser("node-waste", help="[legacy] find node_modules waste")
    sp_nw.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."),
                       help="project root to scan for node_modules waste")

    cp = sub.add_parser("clean", help="preview or execute cleanup")
    cp.add_argument("--items", help="path to JSON file or JSON string with items")
    cp.add_argument("--stdin", action="store_true", help="read items JSON from stdin")
    cp.add_argument("--dry-run", action="store_true", help="preview only, no delete")
    cp.add_argument("--permanent", action="store_true", help="skip trash, permanent delete")
    cp.add_argument("--fast", action="store_true",
                    help="direct delete for large items (default: recycle bin)")
    cp.add_argument("--safety", choices=["safe", "caution", "unsafe"],
                    help="minimum safety level (default: all). safe < caution < unsafe")
    cp.add_argument("--explain", action="store_true",
                    help="show confidence scores and reasons in output")
    cp.add_argument("--min-confidence", type=int, choices=range(1, 101), metavar="0-100",
                    help="only process items with confidence >= this threshold")
    cp.add_argument("--auto-safe", action="store_true",
                    help="only delete items with confidence >= 0.90 AND safety=safe")
    cp.add_argument("--deep", action="store_true",
                    help="full autonomous cleaning cycle: scan → score → filter → execute → verify")
    cp.add_argument("--yes", action="store_true",
                    help="skip confirmation prompt (for --deep mode)")
    cp.add_argument("--strategy", choices=["safe", "aged", "orphan", "all"], default="safe",
                    help="filter strategy for --deep mode (default: safe)")
    cp.add_argument("--path", default=None,
                    help="root path for --deep scan (default: user profile)")

    hp = sub.add_parser("history", help="view cleanup history")
    hp.add_argument("--id", type=int, help="operation ID to inspect")
    hp.add_argument("--limit", type=int, default=20)

    up = sub.add_parser("undo", help="undo a cleanup operation")
    up.add_argument("id", type=int, help="operation ID to undo")

    mp = sub.add_parser("mcp", help="start MCP server for AI tool calls")

    # ── Dedupe strategy for clean command ──
    cp.add_argument("--dedupe", choices=["keep-newest", "keep-first", "keep-smallest"],
                    help="deduplicate: scan path, keep one copy, delete the rest")

    # ── Schedule subcommand ──
    sp_sch = sub.add_parser("schedule", help="manage scheduled cleanup tasks")
    sp_sch.add_argument("--create", action="store_true",
                        help="create a weekly scheduled cleanup")
    sp_sch.add_argument("--remove", action="store_true",
                        help="remove the scheduled cleanup task")
    sp_sch.add_argument("--path", default="C:\\",
                        help="drive or path to clean (default: C:\\)")
    sp_sch.add_argument("--time", default="03:00",
                        help="time to run, e.g. 03:00 (default: 3 AM)")

    # ── Reflex subcommands ──
    rp = sub.add_parser("pulse", help="[REFLEX] instant disk health check")
    rp.add_argument("path", nargs="?", default="C:\\", help="drive to check")
    ac = sub.add_parser("auto-clear", help="[REFLEX] auto-clear cost=none items")
    ac.add_argument("path", nargs="?", default="C:\\", help="root path")
    ac.add_argument("--target-gb", type=float, default=0, help="stop after N GB")

    # ── Reclaim subcommand ──
    rc = sub.add_parser("reclaim", help="full reclaim plan: scan → aggregate → phases → execute")
    rc.add_argument("path", nargs="?", default="C:\\", help="root path")
    rc.add_argument("--phase", help="execute only this cost phase (none/low/medium/high)")
    rc.add_argument("--yes", action="store_true", help="skip confirmation")
    rc.add_argument("--dry-run", action="store_true", help="show plan without executing")

    # ── Import subcommand ──
    imp_p = sub.add_parser("import", help="import cleaner definitions (winapp2)")
    imp_sub = imp_p.add_subparsers(dest="import_type")
    imp_w2 = imp_sub.add_parser("winapp2", help="import Winapp2.ini cleaner definitions")
    imp_w2.add_argument("path", help="path to winapp2.ini file")

    # ── Report subcommand ──
    rp_p = sub.add_parser("report", help="[REPORT] AI-ready structured report of reclaimable space")
    rp_p.add_argument("path", nargs="?", default=os.environ.get("USERPROFILE", "."),
                      help="drive or directory path (default: USERPROFILE)")
    rp_p.add_argument("--cost", choices=["none","low","medium","high","unknown"],
                      help="filter to a single cost phase")
    rp_p.add_argument("--ecosystem", help="filter to an ecosystem group")
    rp_p.add_argument("--min-size-mb", type=int, default=0,
                      help="minimum item size in MB")

    # ── Doctor subcommand ──
    doc = sub.add_parser("doctor", help="[DIAG] Clyan system diagnosis")
    doc.add_argument("--verbose", "-v", action="store_true",
                     help="detailed diagnostics")

    # ── Benchmark subcommand ──
    bm = sub.add_parser("benchmark", help="[PERF] provider benchmark")
    bm.add_argument("path", nargs="?", default="C:\\",
                     help="path to scan (default: C:\\)")

    return p


def cmd_import(args: argparse.Namespace) -> None:
    if args.import_type == "winapp2":
        path = args.path
        if not os.path.isfile(path):
            _out({"error": f"File not found: {path}"})
            return
        try:
            content = open(path, "r", encoding="utf-8").read()
        except Exception:
            try:
                content = open(path, "r", encoding="utf-16-le").read()
            except Exception as e:
                _out({"error": f"Cannot read file: {e}"})
                return
        from .importers.winapp2 import import_winapp2, get_winapp2_stats
        result = import_winapp2(content)
        stats = get_winapp2_stats()
        _out({**result, "stats": stats})
    else:
        _out({"error": f"Unknown import type: {args.import_type}. Supported: winapp2"})


def cmd_trust(args: argparse.Namespace) -> None:
    from .core.history import trust_add, trust_remove, trust_list
    act = args.trust_action
    if act == "add":
        ok = trust_add(args.path, getattr(args, "label", ""), getattr(args, "reason", ""))
        _out({"success": ok, "message": f"Trusted: {args.path}" if ok else "Failed"})
    elif act == "remove":
        ok = trust_remove(args.path)
        _out({"success": ok, "message": f"Removed trust: {args.path}" if ok else "Not found"})
    elif act == "list":
        _out({"trusted_paths": trust_list()})
    else:
        _out({"error": "use: clyan trust add/remove/list"})


def cmd_scan_files(args: argparse.Namespace) -> None:
    from .scan.large_files import LargeFileScanner
    reset_dir_total_cache()
    s = LargeFileScanner(path=args.path, min_size_mb=args.min_size, top_n=args.top)
    result = s.scan()
    d = result.to_dict()
    if getattr(args, "json_mode", False):
        sys.stdout.write(json.dumps(d["items"], ensure_ascii=False) + "\n")
    else:
        _out(d)


def cmd_scan_node_waste(args: argparse.Namespace) -> None:
    from .scan.node_waste import NodeWasteScanner
    reset_dir_total_cache()
    s = NodeWasteScanner(path=args.path)
    result = s.scan()
    _out(result.to_dict())


def cmd_schedule(args: argparse.Namespace) -> None:
    if args.create:
        _schedule_create(args)
    elif args.remove:
        _schedule_remove(args)
    else:
        print("Usage: clyan schedule --create [--time 03:00] [--path C:\\]")
        print("       clyan schedule --remove")


def _schedule_create(args: argparse.Namespace) -> None:
    """Create a Windows scheduled task for weekly cleanup."""
    import subprocess
    python_exe = sys.executable
    clyan_script = os.path.join(os.path.dirname(__file__), "__main__.py")
    if not os.path.exists(clyan_script):
        clyan_script = os.path.join(os.path.dirname(__file__), "cli.py")
    task_name = "ClyanWeeklyCleanup"
    cmd = f'"{python_exe}" -m clyan clean --deep --yes --strategy safe --path "{args.path}"'
    schtask_cmd = [
        "schtasks", "/Create", "/TN", task_name, "/SC", "WEEKLY",
        "/ST", args.time, "/TR", cmd,
        "/F",  # Force overwrite if exists
    ]
    try:
        r = subprocess.run(schtask_cmd, capture_output=True, text=True, creationflags=0x08000000)
        if r.returncode == 0:
            _out({"message": f"Scheduled task '{task_name}' created. Runs weekly at {args.time}."})
        else:
            _out({"error": f"Failed to create task: {r.stderr.strip() or r.stdout.strip()}"})
    except Exception as e:
        _out({"error": f"Failed to create task: {e}"})


def _schedule_remove(args: argparse.Namespace) -> None:
    """Remove the scheduled cleanup task."""
    import subprocess
    task_name = "ClyanWeeklyCleanup"
    try:
        r = subprocess.run(
            ["schtasks", "/Delete", "/TN", task_name, "/F"],
            capture_output=True, text=True, creationflags=0x08000000,
        )
        if r.returncode == 0:
            _out({"message": f"Scheduled task '{task_name}' removed."})
        else:
            _out({"error": f"Failed to remove task: {r.stderr.strip() or r.stdout.strip()}"})
    except Exception as e:
        _out({"error": f"Failed to remove task: {e}"})


def main() -> None:
    global _VERBOSE, CLYAN_CONFIG
    parser = build_parser()
    args, _extra = parser.parse_known_args()
    if getattr(args, "verbose", False):
        _VERBOSE = True
        CLYAN_CONFIG["verbose"] = True
    if getattr(args, "json", False):
            CLYAN_CONFIG["json"] = True

    if args.command == "scan":
        # If --phase specified, use pipeline
        phase = getattr(args, "phase", None)
        if phase:
            from .scan.pipeline import ScanPipeline
            pipe = ScanPipeline(path=getattr(args, "path", "C:\\"))
            phases = {1: pipe.phase1, 2: pipe.phase2_garbage, 3: pipe.phase3_deep}
            result = phases[phase]()
            # Pretty print
            label = result.get("label", f"Phase {phase}")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return

        dispatch = {
            "space": cmd_scan_space,
            "dev-garbage": cmd_scan_dev,
            "browsers": cmd_scan_browsers,
            "system": cmd_scan_system,
            "duplicates": cmd_scan_duplicates,
            "files": cmd_scan_files,
            "packages": cmd_scan_packages,
            "quick": cmd_scan_quick,
            "disk": cmd_scan_disk,
            "node-waste": cmd_scan_node_waste,
        }
        fn = dispatch.get(args.scan_type)
        if fn:
            fn(args)
            return

        # Default: Progressive drill-down scan
        path = getattr(args, "path", "C:\\") or "C:\\"
        from .scan.drill import scan_dir
        result = scan_dir(path)
        _out(result)

    elif args.command == "clean":
        cmd_clean(args)
    elif args.command == "reclaim":
        from .reclaim import reclaim, execute_phase
        plan = reclaim(args.path)
        if args.dry_run or not args.phase:
            # Show plan
            print(f"📋  Reclaim Plan for {args.path}")
            print(f"   Total: {plan['total_size_human']} ({plan['total_items']} items)")
            for p in plan['phases']:
                icon = {"none":"🟢","low":"🟡","medium":"🟠","high":"🔴","unknown":"⚫"}.get(p['cost'],"❓")
                eco = ', '.join([f"{e['ecosystem']}: {e['size_human']}" for e in p.get('ecosystem_breakdown',[])])
                print(f"   {icon}  Phase {p['cost']}: {p['total_size_human']} ({p['item_count']} items) — {eco}")
            rec = plan['recommendation']
            rec = plan["recommendation"]
            print(f"\n{rec}")
            print("---")
        if args.phase:
            result = execute_phase(plan, args.phase, fast=True)
            icon_done = "✅" if result.get('fail_count',0) == 0 else "⚠️"
            print(f"{icon_done}  Phase {args.phase}: {result.get('success_count',0)} cleared, {result.get('fail_count',0)} failed")
            print(f"   Freed: {result.get('total_freed_human','0 B')}")
            print(f"   Actual: {result.get('actual_freed_human','?')}")
        # Always output full JSON
        print(json.dumps(plan if not args.phase else result, ensure_ascii=False, indent=2))
    elif args.command == "history":
        cmd_history(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "benchmark":
        cmd_benchmark(args)
    elif args.command == "undo":
        cmd_undo(args)
    elif args.command == "pulse":
        from .reflex import check_pulse
        result = check_pulse(args.path)
        # Human-readable summary
        status_icon = {"healthy": "🟢", "warning": "🟡", "critical": "🔴"}.get(result["status"], "❓")
        print(f"{status_icon}  Disk {result['path']}: {result['free_gb']} GB free ({result['free_pct']}%)")
        print(f"   Total: {result['total_gb']} GB  |  Used: {result['used_gb']} GB")
        print(f"   Safe reclaimable: {result['safe_reclaimable_gb']} GB  |  Days critical: {result['days_until_critical']}")
        growth = result.get('growth_rate_gb_per_week')
        if growth:
            print(f"   Growth: {growth} GB/week")
        print(f"   Status: {result['status'].upper()}  |  Cached: {result.get('cached',False)}  |  {result.get('ellapsed_ms',0)}ms")
        # Also print JSON for AI consumption
        print("---")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "auto-clear":
        from .reflex import auto_clear_safe
        result = auto_clear_safe(path=args.path, target_gb=args.target_gb)
        icon = "✅" if result.get("items_failed",0) == 0 else "⚠️"
        print(f"{icon}  Auto-clear: {result.get('message','')}")
        print(f"   Items: {result.get('items_cleared',0)} cleared, {result.get('items_failed',0)} failed")
        print(f"   Freed: {result.get('reclaimed_human','0 B')}  |  Actual: {result.get('actual_freed_human','?')}")
        print(f"   Protected skipped: {result.get('protected_paths_skipped',0)}")
        print(f"   Time: {result.get('ellapsed_ms',0)/1000:.1f}s")
        print("---")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.command == "mcp":
        cmd_mcp(args)
    elif args.command == "schedule":
        cmd_schedule(args)
    elif args.command == "trust":
        cmd_trust(args)
    elif args.command == "import":
        cmd_import(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
