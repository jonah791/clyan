import re

_SIZE_SUFFIXES = ["B", "KB", "MB", "GB", "TB", "PB"]

def format_size(bytes_val: int) -> str:
    if bytes_val == 0:
        return "0 B"
    suffix_idx = 0
    value = float(bytes_val)
    while value >= 1024 and suffix_idx < len(_SIZE_SUFFIXES) - 1:
        value /= 1024
        suffix_idx += 1
    return f"{value:.2f} {_SIZE_SUFFIXES[suffix_idx]}"

def parse_size(text: str) -> int:
    text = text.strip().upper()
    m = re.match(r"^([\d.]+)\s*(B|KB|MB|GB|TB|PB)?$", text)
    if not m:
        raise ValueError(f"cannot parse size: {text}")
    value = float(m.group(1))
    unit = m.group(2) or "B"
    multiplier = 1
    for i, s in enumerate(_SIZE_SUFFIXES):
        if s == unit:
            multiplier = 1024 ** i
            break
    return int(value * multiplier)
