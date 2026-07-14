import os
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total





def _scan_ide(root: str) -> list[CacheItem]:
    results = []
    appdata = os.environ.get("APPDATA", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "")

    vscode_caches = [
        (os.path.join(appdata, "Code", "Cache"), "VSCode Cache"),
        (os.path.join(appdata, "Code", "CachedData"), "VSCode CachedData"),
        (os.path.join(appdata, "Code", "CachedExtensionVSIXs"), "VSCode Cached VSIXs"),
        (os.path.join(appdata, "Code", "User", "workspaceStorage"), "VSCode workspace storage"),
        (os.path.join(appdata, "Code - Insiders", "Cache"), "VSCode Insiders Cache"),
        (os.path.join(appdata, "Code - Insiders", "CachedData"), "VSCode Insiders CachedData"),
    ]
    for path, label in vscode_caches:
        if os.path.isdir(path):
            sz = dir_total(path)
            if sz > 0:
                results.append(CacheItem(
                    path=path, size=sz, provider="ide",
                    label=label, safety=SafetyLevel.CAUTION,
                    extra={"type": "vscode"},
                ))

    jetbrains_dir = os.path.join(local_appdata, "JetBrains")
    if os.path.isdir(jetbrains_dir):
        for version in os.listdir(jetbrains_dir):
            # Skip: just the apps/ subdir (not a cache dir itself)
            if version == "apps":
                # Toolbox apps/IDE-version/ch-0/ dirs may have log/cache subdirs
                apps_dir = os.path.join(jetbrains_dir, "apps")
                if os.path.isdir(apps_dir):
                    for ide_name in os.listdir(apps_dir):
                        ide_dir = os.path.join(apps_dir, ide_name)
                        if not os.path.isdir(ide_dir):
                            continue
                        for ch in os.listdir(ide_dir):
                            ch_dir = os.path.join(ide_dir, ch)
                            if not os.path.isdir(ch_dir):
                                continue
                            for sub in ["caches", "index", "tmp", "logs"]:
                                p = os.path.join(ch_dir, sub)
                                if os.path.isdir(p):
                                    sz = dir_total(p)
                                    if sz > 0:
                                        results.append(CacheItem(
                                            path=p, size=sz, provider="ide",
                                            label=f"JetBrains {sub} ({ide_name})",
                                            safety=SafetyLevel.CAUTION,
                                            extra={"type": "jetbrains", "version": ide_name, "sub": sub},
                                        ))
                continue
            for sub in ["caches", "index", "tmp", "logs"]:
                p = os.path.join(jetbrains_dir, version, sub)
                if os.path.isdir(p):
                    sz = dir_total(p)
                    if sz > 0:
                        results.append(CacheItem(
                            path=p, size=sz, provider="ide",
                            label=f"JetBrains {sub} ({version})",
                            safety=SafetyLevel.CAUTION,
                            extra={"type": "jetbrains", "version": version, "sub": sub},
                        ))

    # IntelliJ / PyCharm / WebStorm / CLion / etc. system caches
    ide_system_dirs = [".IntelliJIdea", ".PyCharm", ".WebStorm", ".CLion", ".GoLand", ".DataGrip", ".Rider"]
    for ide_dir in ide_system_dirs:
        p = os.path.join(user_home(), ide_dir, "system", "caches")
        if os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="ide",
                    label=f"{ide_dir} caches",
                    safety=SafetyLevel.CAUTION,
                    extra={"type": "jetbrains"},
                ))

    for pkg_dir in [os.path.join(user_home(), ".vscode", "extensions")]:
        if os.path.isdir(pkg_dir):
            sz = dir_total(pkg_dir)
            if sz > 0:
                results.append(CacheItem(
                    path=pkg_dir, size=sz, provider="ide",
                    label="VS Code extensions",
                    safety=SafetyLevel.CAUTION,
                    extra={"type": "vscode_extensions"},
                ))

    return results


def user_home() -> str:
    return os.environ.get("USERPROFILE", "")


register("ide", _scan_ide)
