import re
with open("clyan/cli.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix C:\) — need to make it C:\\) in source
# In the file:  default: C:\)  (backslash + paren)
# Target:       default: C:\\) (escaped backslash + paren)
# This means replacing literal bytes: C . : . \ . ) with: C . : . \ . \ . )

# Use regex to find 'default: C:\))' and replace with 'default: C:\\))'
content = re.sub(r'default: C:\\)', r'default: C:\\', content)
# The above replaces 'default: C:\)' with 'default: C:\' — need to add back the closing paren
# Actually simpler: find and replace the specific help strings

content = content.replace(
    'help="path to scan (default: C:\\)")',
    'help="path to scan (default: C:\\\\)")'
)

with open("clyan/cli.py", "w", encoding="utf-8") as f:
    f.write(content)
print("done")
