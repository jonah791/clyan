"""System drive detection — single source of truth."""
import os

_SYSTEM_DRIVE: str | None = None


def system_drive() -> str:
    """Detect the Windows system drive (C:/, D:/, etc.)."""
    global _SYSTEM_DRIVE
    if _SYSTEM_DRIVE is not None:
        return _SYSTEM_DRIVE
    # Try SystemDrive env (most reliable)
    sd = os.environ.get("SystemDrive")
    if sd:
        _SYSTEM_DRIVE = sd.rstrip("\\") + "\\"
        return _SYSTEM_DRIVE
    # Derive from WINDIR
    wd = os.environ.get("WINDIR", "").strip()  # e.g., "C:\\Windows"
    if wd:
        drive = wd[:2]  # "C:"
        if drive.endswith(":"):
            _SYSTEM_DRIVE = drive + "\\"
            return _SYSTEM_DRIVE
    # Fallback
    _SYSTEM_DRIVE = "C:\\"
    return "C:\\"


def system_root_path(*parts: str) -> str:
    """Build a path under system drive: system_root_path('Windows') -> 'C:\\Windows'"""
    return os.path.join(system_drive(), *parts)
