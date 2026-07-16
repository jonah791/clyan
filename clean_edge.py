"""Auto clean safe Edge cache"""
import os, shutil

USER = os.path.expandvars("%USERPROFILE%")

for name in ["Cache", "Code Cache"]:
    p = USER + "\\AppData\\Local\\Microsoft\\Edge\\User Data\\Default\\" + name
    if os.path.isdir(p):
        # Count before
        sz = 0
        for dp, _, fs in os.walk(p):
            for f in fs:
                try: sz += os.path.getsize(os.path.join(dp, f))
                except: pass
        print(f"Cleaning {name} ({sz/1e6:.1f} MB)...", end=" ", flush=True)
        for item in os.listdir(p):
            ip = os.path.join(p, item)
            try:
                if os.path.isfile(ip) or os.path.islink(ip):
                    os.remove(ip)
                elif os.path.isdir(ip):
                    shutil.rmtree(ip, ignore_errors=True)
            except: pass
        print("done")

print("Done")
