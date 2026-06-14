import os

_WINDOWS_KNOWN = {}

def _init_win_paths():
    global _WINDOWS_KNOWN
    if _WINDOWS_KNOWN:
        return
    _WINDOWS_KNOWN = {
        "APPDATA": os.environ.get("APPDATA", ""),
        "LOCALAPPDATA": os.environ.get("LOCALAPPDATA", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "WINDIR": os.environ.get("WINDIR", "C:\\Windows"),
        "PROGRAMDATA": os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
        "PUBLIC": os.environ.get("PUBLIC", "C:\\Users\\Public"),
    }

def get_known_path(name: str) -> str:
    _init_win_paths()
    return _WINDOWS_KNOWN.get(name, "")

def get_known_paths() -> dict:
    _init_win_paths()
    return dict(_WINDOWS_KNOWN)

def expand_user_path(path: str) -> str:
    if path.startswith("~"):
        return os.path.expanduser(path)
    return path

def browser_cache_paths() -> dict:
    local_appdata = get_known_path("LOCALAPPDATA")
    appdata = get_known_path("APPDATA")
    return {
        "chrome": os.path.join(local_appdata, "Google", "Chrome", "User Data", "Default", "Cache"),
        "chrome_code_cache": os.path.join(local_appdata, "Google", "Chrome", "User Data", "Default", "Code Cache"),
        "edge": os.path.join(local_appdata, "Microsoft", "Edge", "User Data", "Default", "Cache"),
        "edge_code_cache": os.path.join(local_appdata, "Microsoft", "Edge", "User Data", "Default", "Code Cache"),
        "firefox": os.path.join(appdata, "Mozilla", "Firefox", "Profiles"),
    }

def home_dirs() -> list:
    userprofile = get_known_path("USERPROFILE")
    if not userprofile:
        return []
    entries = []
    for name in os.listdir(userprofile):
        full = os.path.join(userprofile, name)
        if os.path.isdir(full):
            entries.append(full)
    return entries
