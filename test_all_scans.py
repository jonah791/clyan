"""Run all scan commands and display results."""
import subprocess, json, sys

def run(cmd, label, timeout=30):
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            print(f"  [exit={r.returncode}] stderr:\n    {r.stderr[:500]}")
            return None
        d = json.loads(r.stdout)
        return d
    except subprocess.TimeoutExpired:
        print(f"  [TIMEOUT {timeout}s]")
        return None
    except json.JSONDecodeError as e:
        print(f"  [JSON ERROR] {e}")
        print(f"  stdout[:300]: {r.stdout[:300]}")
        return None

# ── 1. scan quick ──
d = run(["python3", "-m", "clyan", "scan", "quick", "C:\\Users\\tr"], "1. scan quick — full scan (user profile)", 30)
if d:
    for cat, label in [("space","Space"),("dev_garbage","DevGarbage"),("browsers","Browsers"),("system","System")]:
        data = d.get(cat, {})
        if isinstance(data, dict):
            sz = data.get("total_size_human","?")
            n = data.get("item_count",0)
            t = data.get("scan_time_ms",0)/1000
            print(f"  {label:12s} {n:4d} items  {sz:>9s}  ({t:.1f}s)")

# ── 2. scan space ──
d = run(["python3", "-m", "clyan", "scan", "space", "C:\\Users\\tr", "--depth", "1", "--top", "8"], "2. scan space — directory tree (depth=1)", 15)
if d:
    print(f"  {d['item_count']} items, {d['total_size_human']}, {d['scan_time_ms']/1000:.1f}s")
    for item in d['items'][:8]:
        print(f"    {item['size_human']:>9s}  {item['path'][:55]}")

# ── 3. scan dev-garbage ──
d = run(["python3", "-m", "clyan", "scan", "dev-garbage"], "3. scan dev-garbage", 15)
if d:
    print(f"  {d['item_count']} items, {d['total_size_human']}, {d['scan_time_ms']/1000:.1f}s")
    for item in d['items'][:8]:
        w = item.get("warning","")
        c = item.get("confidence",0)
        cf = f"  conf={c:.2f}{' ⚠ '+w[:40] if w else ''}"
        print(f"    {item['size_human']:>9s}  {item.get('label','')[:40]:40s}{cf}")

# ── 4. scan system ──
d = run(["python3", "-m", "clyan", "scan", "system"], "4. scan system — Windows temp + recycle bin", 15)
if d:
    print(f"  {d['item_count']} items, {d['total_size_human']}")
    for item in d['items']:
        o = "  [orphan]" if item.get('orphan') else ""
        print(f"    {item['size_human']:>9s}  {item.get('label','')[:50]}{o}")

# ── 5. scan browsers ──
d = run(["python3", "-m", "clyan", "scan", "browsers"], "5. scan browsers", 10)
if d:
    print(f"  {d['item_count']} items, {d['total_size_human']}")
    for item in d['items']:
        print(f"    {item['size_human']:>9s}  {item.get('label','')[:50]}")

# ── 6. scan files (large files) ──
d = run(["python3", "-m", "clyan", "scan", "files", "--min-size", "200", "--top", "6"], "6. scan files — large files >200MB", 30)
if d:
    print(f"  {d['item_count']} big files")
    for item in d['items']:
        print(f"    {item['size_human']:>9s}  {item['path'][:60]}")

# ── 7. scan duplicates ──
d = run(["python3", "-m", "clyan", "scan", "duplicates", "--min-size-mb", "10", "--top", "5"], "7. scan duplicates (>10MB, top 5 groups)", 30)
if d:
    print(f"  {d['item_count']} dupe groups")
    for item in d['items'][:5]:
        print(f"    keep: {item['keep'][:55]}")
        for dup in item['duplicates'][:2]:
            print(f"      x  {dup['path'][:55]}  ({item['savings_human']})")

# ── 8. scan disk ──
d = run(["python3", "-m", "clyan", "scan", "disk", "C:\\", "--depth", "1"], "8. scan disk C: — overview", 60)
if d:
    disk = d.get("disk",{})
    print(f"  {disk.get('total_human','?')} total, {disk.get('usage_percent','?')}% used")
    for node in d.get("top_dirs",[])[:8]:
        pct = node["size"] / max(disk.get("total",1),1) * 100
        print(f"    {node['name']:28s} {node['size_human']:>9s}  {pct:.1f}%")

print(f"\n{'='*55}")
print("  All scans completed ✓")
print(f"{'='*55}")
