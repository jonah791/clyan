"""Deep safety assessment of C drive cleanable items"""
import os, time, json

USER = os.path.expandvars("%USERPROFILE%")
now = time.time()

print("=== 深度安全评估 ===\n")

# 1. npx binaries
npx = USER + "\\AppData\\Local\\npm-cache\\_npx"
if os.path.isdir(npx):
    sz = 0
    bins = []
    for d in os.listdir(npx):
        dp = os.path.join(npx, d)
        if os.path.isdir(dp):
            for root, _, files in os.walk(dp):
                for f in files:
                    try: sz += os.path.getsize(os.path.join(root, f))
                    except: pass
            bins.append(d[:40])
    print("1. npx 二进制缓存")
    print(f"   大小: {sz/1e6:.1f} MB")
    print(f"   包含: {bins[:5]}")
    print("   安全等级: \U0001f7e2 零风险")
    print("   理由: 一次性下载的可执行文件，npm 会自动重新下载")
    print()

# 2. npm cache by year
cacache = USER + "\\AppData\\Local\\npm-cache\\_cacache"
if os.path.isdir(cacache):
    year_sz = {}
    total = 0
    for entry in os.listdir(cacache):
        ep = os.path.join(cacache, entry)
        if os.path.isdir(ep):
            try: yr = time.strftime("%Y", time.localtime(os.path.getmtime(ep)))
            except: yr = "unknown"
            sub = 0
            for root, _, files in os.walk(ep):
                for f in files:
                    try: sub += os.path.getsize(os.path.join(root, f))
                    except: pass
            year_sz[yr] = year_sz.get(yr, 0) + sub
            total += sub
    print("2. npm 包缓存 (_cacache)")
    print(f"   大小: {total/1e6:.1f} MB")
    for yr, sz in sorted(year_sz.items()):
        print(f"     {yr}: {sz/1e6:.1f} MB ({sz*100//total}%)")
    old = sum(sz for yr, sz in year_sz.items() if yr.isdigit() and int(yr) < 2025)
    current = sum(sz for yr, sz in year_sz.items() if yr.isdigit() and int(yr) >= 2025)
    if old > 0:
        print(f"   <2025 (旧): {old/1e6:.1f} MB \U0001f7e2 安全可删（不再使用的版本）")
    if current > 0:
        print(f"   2025+ (新): {current/1e6:.1f} MB \U0001f7e1 缓存当前版本，npm install 加速用")
    print()

# 3. pip cache by age
pip = USER + "\\AppData\\Local\\pip\\cache"
if os.path.isdir(pip):
    ages = {"0-30d": 0, "31-90d": 0, "91-180d": 0, "181-365d": 0, ">365d": 0}
    total_pip = 0
    for root, _, files in os.walk(pip):
        for f in files:
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
                total_pip += st.st_size
                age = (now - st.st_mtime) / 86400
                if age <= 30: ages["0-30d"] += st.st_size
                elif age <= 90: ages["31-90d"] += st.st_size
                elif age <= 180: ages["91-180d"] += st.st_size
                elif age <= 365: ages["181-365d"] += st.st_size
                else: ages[">365d"] += st.st_size
            except: pass
    print("3. pip wheel 缓存")
    print(f"   大小: {total_pip/1e6:.1f} MB")
    for k, v in ages.items():
        if v > 0:
            print(f"     {k}: {v/1e6:.1f} MB")
    old_pip = ages[">365d"] + ages["181-365d"]
    recent_pip = ages["0-30d"] + ages["31-90d"]
    if old_pip > 0:
        print(f"   >180d: {old_pip/1e6:.1f} MB \U0001f7e2 安全可删（旧版本 wheel）")
    if recent_pip > 0:
        print(f"   <90d: {recent_pip/1e6:.1f} MB \U0001f7e1 近期使用，建议保留")
    print()

# 4. npm global
npm_global = USER + "\\AppData\\Local\\npm-cache"
if os.path.isdir(npm_global):
    total_npm = 0
    for root, _, files in os.walk(npm_global):
        for f in files:
            try: total_npm += os.path.getsize(os.path.join(root, f))
            except: pass
    print("4. npm 全局缓存 (npm-cache)")
    npx_sz = 0
    cacache_sz = 0
    for d in os.listdir(npm_global):
        dp = os.path.join(npm_global, d)
        if os.path.isdir(dp):
            sub = 0
            for r, _, fs in os.walk(dp):
                for f in fs:
                    try: sub += os.path.getsize(os.path.join(r, f))
                    except: pass
            if d == "_npx": npx_sz = sub
            elif d == "_cacache": cacache_sz = sub
    other_npm = total_npm - npx_sz - cacache_sz
    print(f"   总大小: {total_npm/1e6:.1f} MB")
    print(f"     _npx: {npx_sz/1e6:.1f} MB")
    print(f"     _cacache: {cacache_sz/1e6:.1f} MB")
    print(f"     其他: {other_npm/1e6:.1f} MB")
    print()

# 5. Summary
print("=== 清理建议 ===\n")
print("\U0001f7e2 零风险（立即删）:")
print(f"   npx 二进制: ~{npx_sz/1e6:.1f} MB" if 'npx_sz' in dir() else "   npx: N/A")
print(f"   npm 旧缓存 (<2025): ~{old/1e6:.1f} MB" if 'old' in dir() else "")
print(f"   pip 旧 wheel (>180d): ~{old_pip/1e6:.1f} MB" if 'old_pip' in dir() else "")

print("\n\U0001f7e1 适度安全（可选）:")
if 'current' in dir():
    print(f"   npm 新缓存 (2025+): {current/1e6:.1f} MB")
if 'recent_pip' in dir():
    print(f"   pip 新 wheel: {recent_pip/1e6:.1f} MB")

print("\n\U0001f534 高重建成本（不推荐）:")
print(f"   全部 npm 缓存 (npm install 需全部重下)")
print(f"   全部 pip 缓存 (pip install 需全部重下)")
