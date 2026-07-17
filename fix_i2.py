"""Fix hardcoded C:\ in scanner files using chr(92) to avoid escape issues."""
import os

BS = chr(92)  # backslash
OLD_NEW = [
    (f'"C:{BS}{BS}Windows"',      'win_path("Windows")'),
    (f'"C:{BS}{BS}Program Files"', 'win_path("Program Files")'),
    (f'"C:{BS}{BS}Program Files (x86)"', 'win_path("Program Files (x86)")'),
    (f'"C:{BS}{BS}ProgramData"',   'win_path("ProgramData")'),
    (f'"C:{BS}{BS}$Recycle.Bin"',  'win_path("$Recycle.Bin")'),
    (f'"C:{BS}{BS}System Volume Information"', 'win_path("System Volume Information")'),
    (f'"C:{BS}{BS}Recovery"',      'win_path("Recovery")'),
    (f'"C:{BS}{BS}Boot"',          'win_path("Boot")'),
    (f'"C:{BS}{BS}Documents and Settings"', 'win_path("Documents and Settings")'),
]

TARGETS = [
    "clyan/scan/large_files.py",
    "clyan/scan/dev_garbage.py",
    "clyan/scan/duplicates.py",
    "clyan/scan/node_waste.py",
    "clyan/scan/fast_scanner.py",
    "clyan/scan/providers/win_deep.py",
    "clyan/scan/providers/windows_extra.py",
    "clyan/core/config.py",
]

IMPORT_TO_ADD = 'from ..utils.system_drive import system_root_path as win_path'

total = 0
for fp in TARGETS:
    if not os.path.isfile(fp):
        print(f"SKIP {os.path.basename(fp)}")
        continue
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Add import if needed
    if IMPORT_TO_ADD not in content:
        lines = content.split('\n')
        last_import = 0
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith('import ') or s.startswith('from '):
                last_import = i
        lines.insert(last_import + 1, IMPORT_TO_ADD)
        content = '\n'.join(lines)
    
    # Replace paths
    count = 0
    for old, new in OLD_NEW:
        if old in content:
            content = content.replace(old, new)
            count += 1
    
    if count:
        with open(fp, 'w', encoding='utf-8') as f:
            f.write(content)
        total += count
        print(f"  {os.path.basename(fp)}: {count} replacements")
    else:
        print(f"  {os.path.basename(fp)}: no changes")

print(f"\nTotal: {total} replacements")
