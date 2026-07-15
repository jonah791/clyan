import sys, re

content = open(sys.argv[1], 'r', encoding='utf-8').read()

# Fix multi-line f-string (the actual syntax error)
content = content.replace(
    '            print(f"\n{plan[\'recommendation\']}")',
    '            print(f"\\n{plan[\'recommendation\']}")'
)

# If that didn't work, find any multi-line f-string
lines = content.split('\n')
for i, line in enumerate(lines):
    stripped = line.strip()
    # Find lines that are just print(f" continuing on next line
    if stripped == 'print(f"':
        # The f-string continues to next line
        if i + 1 < len(lines):
            next_line = lines[i + 1].strip()
            if next_line.startswith('{'):
                # Fix by combining
                lines[i] = '            rec = plan["recommendation"]'
                lines[i + 1] = '            print(f"\\n{rec}")'

content = '\n'.join(lines)

# Fix all default="C:\" patterns (which cause unterminated string)
# The Python source needs to have \\ for a literal backslash
content = re.sub(r'default="C:\\\\"', 'default="C:\\\\\\\\"', content)

# Fix schedule usage line
content = content.replace(
    'print("Usage: clyan schedule --create [--time 03:00] [--path C:]")',
    'print("Usage: clyan schedule --create [--time 03:00] [--path C:]")'
)

open(sys.argv[1], 'w', encoding='utf-8').write(content)
print('fixed')
