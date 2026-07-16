"""Winapp2: map default-category cleaners by Detect path."""
import sqlite3, os, json
from clyan.core.history import _get_db

db = _get_db()
conn = sqlite3.connect(db)

# Check if winapp2 table exists
cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in cur.fetchall()]
print("Tables:", tables)

if "winapp2_cleaners" not in tables:
    print("Winapp2 table not found. Import winapp2.ini first:")
    print("  cd clyan && python3 -m clyan import winapp2 winapp2.ini")
    conn.close()
    exit()

# Category mapping by path keyword
PATH_RULES = [
    ("browser_cache", ["chrome", "chromium", "firefox", "mozilla", "edge", "opera", "safari"]),
    ("windows_system", ["\\windows\\", "windows\\", "winnt\\", "system32", "syswow64", "winsxs"]),
    ("windows_temp", ["\\temp\\", "\\tmp\\", "prefetch", "\\recent", "\\recycle", ".log"]),
    ("app_cache", ["appdata\\local\\", "appdata\\roaming\\", "\\cache\\"]),
    ("dev_garbage", ["node_modules", "\\.npm", "\\pip\\cache", "__pycache__", "\\target", "\\build\\"]),
    ("ml_cache", ["huggingface", "\\.ollama", "models\\"]),
    ("java", ["java\\", "jre\\", "jdk\\"]),
    ("game_cache", ["steam\\", "epic games\\", "shader\\"]),
    ("font_cache", ["\\fonts\\"]),
]

cur = conn.execute("SELECT section_name, file_keys, detect, detectfile FROM winapp2_cleaners WHERE category='winapp2'")
rows = cur.fetchall()
print(f"Unclassified cleaners: {len(rows)}")

if len(rows) == 0:
    print("All already classified!")
    conn.close()
    exit()

updates = {}
for row in rows:
    name = row[0]
    fks_raw = row[1]
    detect = row[2] or ""
    detectfile = row[3] or ""

    search_text = (detect.lower() + " " + detectfile.lower() + " " + name.lower())
    if fks_raw and fks_raw.startswith("["):
        try:
            for fk in json.loads(fks_raw):
                p = fk.get("path", "").replace("[", "").replace("]", "").replace("*", "")
                search_text += " " + p.lower()
        except json.JSONDecodeError:
            pass

    for cat, keywords in PATH_RULES:
        for kw in keywords:
            if kw in search_text:
                updates[name] = cat
                break
        if name in updates:
            break

print(f"Auto-mapped: {len(updates)}")

for name, cat in list(updates.items())[:10]:
    print(f"  {name[:35]:35s} → {cat}")

updated = 0
for name, cat in updates.items():
    conn.execute("UPDATE winapp2_cleaners SET category=? WHERE section_name=? AND category='winapp2'",
                 (cat, name))
    updated += 1
conn.commit()

cur = conn.execute("SELECT category, COUNT(*) FROM winapp2_cleaners GROUP BY category ORDER BY COUNT(*) DESC")
for cat, cnt in cur.fetchall():
    print(f"  {cat}: {cnt}")
print(f"\nUpdated: {updated}")
conn.close()
