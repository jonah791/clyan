import os
from enum import Enum


class DangerLevel(Enum):
    SAFE = "safe"
    CAUTION = "caution"
    UNSAFE = "unsafe"

    def label(self) -> str:
        return {
            "safe": "Safe — re-downloadable cache/artifact. No data loss.",
            "caution": "Caution — may cause rebuild or require app reinstall.",
            "unsafe": "Unsafe — contains config, credentials, or valuable data.",
        }[self.value]

    @staticmethod
    def for_dirname(name: str) -> "DangerLevel":
        safe_dirs = {"__pycache__", ".mypy_cache", ".pytest_cache",
                      ".ruff_cache", ".cache", ".parcel-cache",
                      "coverage", "npm_cache", "pip_cache",
                      "bun_cache", "go_cache", "pub_cache",
                      "thumbnail_cache", "system_temp", "recycle_bin",
                      ".gradle"}
        caution_dirs = {"node_modules", ".venv", "venv", ".env", "env", ".direnv",
                        "vscode_extensions", "vscode", "jetbrains",
                        ".dart_tool", ".fvm", "docker", "android_studio",
                        "vsstudio", "cargo_registry", "dotnet_ngen",
                        "browser_cache", "delivery_opt", "font_cache",
                        "prefetch", "windows_update",
                        "target", "build", "dist", "out",
                        ".next", ".turbo", ".nuxt", ".svelte-kit", ".expo"}
        if name in safe_dirs:
            return DangerLevel.SAFE
        if name in caution_dirs:
            return DangerLevel.CAUTION
        return DangerLevel.UNSAFE


class ProtectedPath:
    def __init__(self, path: str, depth: int = 0, case_insensitive: bool = True):
        self.path = os.path.normpath(path).lower() if case_insensitive else os.path.normpath(path)
        self.depth = depth
        self.case_insensitive = case_insensitive

    def matches(self, target: str) -> bool:
        target = os.path.normpath(target)
        if self.case_insensitive:
            target = target.lower()
            path = self.path
        else:
            path = self.path

        if target == path:
            return True

        path_with_sep = path + os.sep
        target_with_sep = target + os.sep

        # target is a child of this protected path
        if target.startswith(path_with_sep):
            if self.depth < 0:  # any depth
                return True
            relative = target[len(path_with_sep):]
            levels = relative.count(os.sep) + 1 if relative else 0
            return levels <= self.depth

        # target is a parent of this protected path (user wants to delete a container)
        if path.startswith(target_with_sep):
            return True

        return False


class ExemptPath:
    def __init__(self, dirname: str, not_under: list[str] = None):
        self.dirname = dirname.lower()
        self.not_under = [p.lower() for p in (not_under or [])]

    def matches(self, target: str) -> bool:
        target_lower = target.lower()
        parts = target_lower.replace(os.sep, "/").split("/")
        if self.dirname not in parts:
            return False
        # If this exempt path has parent exceptions, verify we're NOT under any
        if self.not_under:
            for forbidden in self.not_under:
                if forbidden in target_lower:
                    return False
        return True


_PROTECTED: list[ProtectedPath] = []
_EXEMPT: list[ExemptPath] = []


def _init():
    if _PROTECTED:
        return

    userprofile = os.environ.get("USERPROFILE", "C:\\Users\\unknown").lower()

    # Global package managers — protect installed packages, allow cache
    appdata = os.environ.get("APPDATA", "").lower()
    if appdata:
        _PROTECTED.append(ProtectedPath(os.path.join(appdata, "npm"), depth=-1))

    _PROTECTED.extend([
        # System roots — depth any = protect everything inside
        ProtectedPath("C:\\", depth=0),
        ProtectedPath("C:\\Windows", depth=-1),
        ProtectedPath("C:\\Program Files", depth=-1),
        ProtectedPath("C:\\Program Files (x86)", depth=-1),
        ProtectedPath("C:\\ProgramData", depth=-1),
        ProtectedPath("C:\\Recovery", depth=-1),
        ProtectedPath("C:\\$Recycle.Bin", depth=-1),
        ProtectedPath("C:\\System Volume Information", depth=-1),
        ProtectedPath("C:\\Boot", depth=-1),
        ProtectedPath("C:\\Documents and Settings", depth=-1),

        # User profile — protect at depth 1 (direct children, not sub-items of exempt dirs)
        ProtectedPath(userprofile, depth=1),

        # User content dirs — protect all content (depth -1)
        ProtectedPath(os.path.join(userprofile, "Desktop"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Documents"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Pictures"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Music"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Videos"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Downloads"), depth=0),
        ProtectedPath(os.path.join(userprofile, "OneDrive"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Favorites"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Links"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Saved Games"), depth=-1),
        ProtectedPath(os.path.join(userprofile, "Searches"), depth=-1),

        # Config dirs — never touch these
        ProtectedPath(os.path.join(userprofile, ".ssh"), depth=-1),
        ProtectedPath(os.path.join(userprofile, ".gnupg"), depth=-1),
        ProtectedPath(os.path.join(userprofile, ".aws"), depth=-1),
        ProtectedPath(os.path.join(userprofile, ".azure"), depth=-1),
        ProtectedPath(os.path.join(userprofile, ".gcloud"), depth=-1),
        ProtectedPath(os.path.join(userprofile, ".kube"), depth=-1),
        ProtectedPath(os.path.join(userprofile, ".docker"), depth=-1),
        ProtectedPath(os.path.join(userprofile, ".config"), depth=0),

        # VCS dirs — protect .git, .svn, .hg anywhere (relative paths)
        ProtectedPath(".git", depth=-1, case_insensitive=False),
        ProtectedPath(".svn", depth=-1, case_insensitive=False),
        ProtectedPath(".hg", depth=-1, case_insensitive=False),
        ProtectedPath(".bzr", depth=-1, case_insensitive=False),
    ])

    _EXEMPT.extend([
        ExemptPath("Temp"),
        ExemptPath("tmp"),
        ExemptPath("cache"),
        ExemptPath("__pycache__"),
        ExemptPath("node_modules", not_under=["roaming\\npm"]),
        ExemptPath("target", not_under=["program files"]),
        ExemptPath(".cache"),
        ExemptPath("build", not_under=["roaming\\npm"]),
        ExemptPath("dist", not_under=["roaming\\npm"]),
        ExemptPath(".next"),
        ExemptPath(".turbo", not_under=["roaming\\npm"]),
        ExemptPath(".gradle"),
        ExemptPath(".mypy_cache"),
        ExemptPath(".pytest_cache"),
        ExemptPath(".ruff_cache"),
        ExemptPath(".venv"),
        ExemptPath("venv"),
        ExemptPath(".dart_tool"),
        ExemptPath("npm-cache"),
        ExemptPath("pnpm", not_under=["roaming\\npm"]),
        ExemptPath(".bun"),
        ExemptPath("CachedData"),
        ExemptPath("CachedExtensionVSIXs"),
        ExemptPath("ComponentModelCache"),
        ExemptPath("Code Cache"),
        ExemptPath("GPUCache"),
        ExemptPath("NativeImages_v4", not_under=["windows"]),
        ExemptPath("NativeImages_v2", not_under=["windows"]),
        ExemptPath("Prefetch", not_under=["windows"]),
        ExemptPath("FontCache", not_under=["windows"]),
        ExemptPath("DeliveryOptimization", not_under=["windows"]),
        ExemptPath("SoftwareDistribution", not_under=["windows"]),
        ExemptPath("catroot2", not_under=["windows"]),
        ExemptPath("assembly", not_under=["windows"]),
    ])


def is_protected(path: str) -> bool:
    _init()
    norm = os.path.normpath(path)

    # Find all matching protection rules
    matched_protections = [pp for pp in _PROTECTED if pp.matches(norm)]
    if not matched_protections:
        return False

    # Check if ANY exemption applies AND is not blocked by not_under
    for ex in _EXEMPT:
        if ex.matches(norm):
            return False

    return True


def _classify_path(norm: str) -> DangerLevel:
    """Walk path components from right to left, classify by first match."""
    parts = norm.lower().replace(os.sep, "/").split("/")
    for i in range(len(parts) - 1, -1, -1):
        level = DangerLevel.for_dirname(parts[i])
        if level != DangerLevel.UNSAFE:
            return level
    return DangerLevel.UNSAFE


def danger_for_path(path: str) -> DangerLevel:
    _init()
    norm = os.path.normpath(path)

    # Protected & not exempt → UNSAFE
    if is_protected(norm):
        for ex in _EXEMPT:
            if ex.matches(norm):
                break
        else:
            return DangerLevel.UNSAFE

    # Walk path components, return first known classification
    level = _classify_path(norm)
    if level != DangerLevel.UNSAFE:
        return level

    # Under an exempt path → safe
    for ex in _EXEMPT:
        if ex.matches(norm):
            return DangerLevel.SAFE

    return DangerLevel.UNSAFE


SAFE_DELETE_DEFAULTS = {
    "use_trash": True,
    "max_items_preview": 200,
    "confirm_threshold_gb": 1.0,
}


def get_protected_summary() -> dict:
    _init()
    return {
        "protected_roots": len([p for p in _PROTECTED if p.depth == -1 or p.depth > 0]),
        "exempt_patterns": len(_EXEMPT),
        "total_rules": len(_PROTECTED) + len(_EXEMPT),
    }
