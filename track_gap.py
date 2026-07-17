"""Full C: scan using single-pass walk."""
import os, sys, json
sys.path.insert(0, "clyan")
from clyan.scan.disk_summary import scan_disk

print("Single-pass full scan of C:... (up to 120s)", flush=True)
r = scan_disk("C:\\", full=True, top_n=25)
d = r.to_dict()
ga = d["gap_analysis"]

print(f"\n{'='*60}")
print(f"C:  {d['disk']['total_human']} total")
print(f"已用: {d['disk']['used_human']}  空闲: {d['disk']['free_human']}")
print(f"扫描: {d['scan_time_ms']/1000:.1f}s")
print(f"模式: {'全量遍历' if d.get('full') else '有界深度'}")
print(f"{'='*60}")

print(f"\n--- 空间去向 ---")
print(f"  已扫描总量:     {ga['accounted_total_human']:>12s}")
print(f"  差距:           {ga['gap_human']:>12s}  ({ga['gap_pct']}%)")
print(f"  不可访问目录:   {ga['inaccessible_count']}")
print(f"  超时:           {ga.get('timeout', False)}")

print(f"\n--- 顶层目录 (前 25) ---")
for nd in d["top_dirs"][:25]:
    pct = nd["size"] / d["disk"]["used"] * 100
    print(f"  {nd['size_human']:>12s}  {pct:5.1f}%  {nd['name']}")

print(f"\n--- 根目录大文件 ---")
for rf in d.get("root_files", []):
    print(f"  {rf['size_human']:>12s}  {rf['name']}")

print(f"\n--- 不可访问目录 ---")
for x in d.get("inaccessible", [])[:8]:
    p = x["path"].split("\\")[-1]
    print(f"  [denied]  {p}")
