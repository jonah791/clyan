"""Interactive safe cleanup"""
import os, shutil, time

USER = os.path.expandvars("%USERPROFILE%")
targets = []

# Edge caches
for name in ["Cache", "Code Cache"]:
    p = USER + "\\AppData\\Local\\Microsoft\\Edge\\User Data\\Default\\" + name
    if os.path.isdir(p):
        sz = 0
        for dp, _, fs in os.walk(p):
            for f in fs:
                try: sz += os.path.getsize(os.path.join(dp, f))
                except: pass
        targets.append((p, sz, name))
        print(f"  {name:25s} {sz/1e6:.1f} MB")

# Temp old files
temp = USER + "\\AppData\\Local\\Temp"
if os.path.isdir(temp):
    now = time.time()
    old_sz = 0
    old_items = 0
    for root, dirs, files in os.walk(temp):
        for f in files:
            fp = os.path.join(root, f)
            try:
                if (now - os.path.getmtime(fp)) / 86400 > 7:
                    old_sz += os.path.getsize(fp)
                    old_items += 1
            except: pass
        depth = root.count(os.sep) - temp.count(os.sep)
        if depth > 2:
            dirs.clear()
    if old_items > 0:
        targets.append((temp, old_sz, "Temp (old files >7d)"))
        print(f"  Temp old files (>7d):    {old_items} items, {old_sz/1e6:.1f} MB")

total = sum(sz for _, sz, _ in targets)
print(f"\nTotal safe reclaimable: {total/1e6:.1f} MB ({len(targets)} groups)")
print(f"\n1. Clean all ({total/1e6:.1f} MB)")
print("2. Skip")
choice = input("Choice [1/2]: ").strip()
if choice == "1":
    freed = 0
    for path, sz, name in targets:
        print(f"  Cleaning {name}...", end=" ", flush=True)
        if os.path.isdir(path):
            for item in os.listdir(path):
                ip = os.path.join(path, item)
                try:
                    if os.path.isfile(ip) or os.path.islink(ip):
                        os.remove(ip)
                    elif os.path.isdir(ip):
                        shutil.rmtree(ip, ignore_errors=True)
                except: pass
        print("done")
        freed += sz
    print(f"\nFreed: {freed/1e6:.1f} MB")
else:
    print("Skipped")
