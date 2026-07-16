"""Clean safe items: browsers + system temp"""
import os, shutil, time

targets = {
    "Edge Cache": os.path.expandvars("%USERPROFILE%\\AppData\\Local\\Microsoft\\Edge\\User Data\\Default\\Cache"),
    "Edge Code Cache": os.path.expandvars("%USERPROFILE%\\AppData\\Local\\Microsoft\\Edge\\User Data\\Default\\Code Cache"),
    "Windows Temp": os.path.expandvars("%USERPROFILE%\\AppData\\Local\\Temp"),
    "Recycle Bin": "shell:RecycleBinFolder",
}

print("=== 安全清理预览 ===")
for name, path in targets.items():
    if os.path.isdir(path):
        try:
            sz = sum(os.path.getsize(os.path.join(dp, f)) for dp, _, fs in os.walk(path) for f in fs)
            print(f"  {name:20s} {sz/1e6:.1f} MB")
        except:
            print(f"  {name:20s} (error calculating)")
    else:
        print(f"  {name:20s} (not accessible as path)")

free_before = sum(
    c.total for c in os.scandir("C:\\") if False
)
