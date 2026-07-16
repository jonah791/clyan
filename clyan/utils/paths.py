"""Path utilities — centralize path handling to eliminate \\u escape hell.

All paths in Clyan should go through these helpers:
  - p()      normalize any path to pathlib.Path
  - pf()     format path for display (forward slashes)
  - pexpand() expand env vars safely
  - pcat()   join path segments
"""
import os
from pathlib import Path, PureWindowsPath


def p(*segments: str) -> Path:
    """Normalize one or more path segments into a Path object.
    
    Handles mixed separators, env vars, and relative paths.
    Example: p("C:\\\\Users", "%USERPROFILE%\\\\AppData") -> Path("C:/Users/tr/AppData")
    """
    joined = os.path.join(*segments) if segments else "."
    expanded = os.path.expandvars(joined)
    return Path(expanded).resolve()


def pf(*segments: str) -> str:
    """Format path(s) for display — always forward slashes, user-friendly.
    
    Replaces %USERPROFILE% with ~ for display.
    Example: pf("C:\\\\Users\\\\tr\\\\AppData") -> "C:/Users/tr/AppData"
    """
    path = p(*segments)
    result = path.as_posix()
    # Shorten user profile to ~ for readability
    user = os.path.expandvars("%USERPROFILE%").replace("\\", "/")
    if result.startswith(user):
        result = "~" + result[len(user):]
    return result


def pshort(path: str, maxlen: int = 60) -> str:
    """Shorten path for display, truncating middle if needed."""
    pstr = pf(path)
    if len(pstr) <= maxlen:
        return pstr
    half = (maxlen - 3) // 2
    return pstr[:half] + "..." + pstr[-half:]


def pcat(*segments: str) -> Path:
    """Join path segments and normalize."""
    return p(os.path.join(*segments))


def pnorm(path: str) -> str:
    """Normalize path string without converting to Path."""
    return os.path.normpath(os.path.expandvars(path))


def psuffix(path: str, suffix: str) -> Path:
    """Add a suffix to a path (e.g. .json cache file)."""
    return p(str(p(path)) + suffix)


def pdirname(path: str) -> str:
    """Get directory name as forward-slash string."""
    return pf(os.path.dirname(path))


def pbasename(path: str) -> str:
    """Get base name."""
    return os.path.basename(path)


def browser_cache_paths() -> dict[str, str]:
    """Return dict of known browser cache directory paths.
    
    Keys: chrome, chrome_code_cache, edge, edge_code_cache, firefox
    Values: absolute paths to cache dirs, or empty string if not found.
    """
    user = os.path.expandvars("%USERPROFILE%")
    local = os.path.join(user, "AppData", "Local")
    
    # Edge
    edge_data = os.path.join(local, "Microsoft", "Edge", "User Data", "Default")
    
    # Chrome
    chrome_data = os.path.join(local, "Google", "Chrome", "User Data", "Default")
    
    # Firefox
    firefox_profiles = os.path.join(user, "AppData", "Roaming", "Mozilla", "Firefox", "Profiles")
    firefox_cache = ""
    if os.path.isdir(firefox_profiles):
        for prof in os.listdir(firefox_profiles):
            prof_cache = os.path.join(firefox_profiles, prof, "cache2")
            if os.path.isdir(prof_cache):
                firefox_cache = prof_cache
                break
    
    return {
        "edge": os.path.join(edge_data, "Cache") if os.path.isdir(os.path.join(edge_data, "Cache")) else "",
        "edge_code_cache": os.path.join(edge_data, "Code Cache") if os.path.isdir(os.path.join(edge_data, "Code Cache")) else "",
        "chrome": os.path.join(chrome_data, "Cache") if os.path.isdir(os.path.join(chrome_data, "Cache")) else "",
        "chrome_code_cache": os.path.join(chrome_data, "Code Cache") if os.path.isdir(os.path.join(chrome_data, "Code Cache")) else "",
        "firefox": firefox_cache,
    }
