"""Test clean mode."""
import os, sys
sys.path.insert(0, "clyan")
from clyan.scan.disk_summary import scan_disk

r = scan_disk(os.environ["USERPROFILE"], full=True, clean=True, top_n=15)
d = r.to_dict()
total_cln = sum(n.get("cleanable", 0) for n in d["top_dirs"])
total_sz = sum(n.get("size", 0) for n in d["top_dirs"])
print(f"Users: {len(d['top_dirs'])} dirs, {total_sz/1e9:.2f} GB total")
print(f"Cleanable: {total_cln/1e9:.2f} GB ({total_cln/max(total_sz,1)*100:.1f}%)")
print()
for nd in d["top_dirs"][:5]:
    cln = nd.get("cleanable", 0)
    if cln > 1e6:
        pct = nd.get("cleanable_pct", 0)
        print(f"  {nd['size_human']:>10s}  cleanable {cln/1e9:.2f}GB ({pct}%)  {nd['name']}")
