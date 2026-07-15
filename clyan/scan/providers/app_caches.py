import os
import glob
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total





def _scan_discord(root: str) -> list[CacheItem]:
    results = []
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")

    for base in [
        os.path.join(appdata, "discord"),
        os.path.join(local, "Discord"),
    ]:
        if os.path.isdir(base):
            for sub in ["Cache", "Code Cache", "GPUCache", "Local Storage"]:
                p = os.path.join(base, sub)
                if os.path.isdir(p):
                    sz = dir_total(p)
                    if sz > 0:
                        results.append(CacheItem(
                            path=p, size=sz, provider="app_cache",
                            label=f"Discord {sub}", safety=SafetyLevel.SAFE,
                            extra={"type": "discord"},
                        ))
    return results


def _scan_slack(root: str) -> list[CacheItem]:
    results = []
    appdata = os.environ.get("APPDATA", "")

    slack_dir = os.path.join(appdata, "Slack")
    if os.path.isdir(slack_dir):
        for sub in ["Cache", "Code Cache", "GPUCache", "Service Worker",
                     "Local Storage", "Session Storage", "blob_storage"]:
            p = os.path.join(slack_dir, sub)
            if os.path.isdir(p):
                sz = dir_total(p)
                if sz > 0:
                    results.append(CacheItem(
                        path=p, size=sz, provider="app_cache",
                        label=f"Slack {sub}", safety=SafetyLevel.SAFE,
                        extra={"type": "slack"},
                    ))
    return results


def _scan_teams(root: str) -> list[CacheItem]:
    results = []
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")

    for base in [
        os.path.join(appdata, "Microsoft", "Teams"),
        os.path.join(local, "Microsoft", "Teams"),
    ]:
        if os.path.isdir(base):
            for sub in ["Cache", "Code Cache", "GPUCache", "blob_storage",
                         "Local Storage", "Session Storage", "databases",
                         "IndexedDB", "tmp"]:
                p = os.path.join(base, sub)
                if os.path.isdir(p):
                    sz = dir_total(p)
                    if sz > 0:
                        results.append(CacheItem(
                            path=p, size=sz, provider="app_cache",
                            label=f"Teams {sub}", safety=SafetyLevel.SAFE,
                            extra={"type": "teams"},
                        ))
    return results


def _scan_wechat(root: str) -> list[CacheItem]:
    results = []
    local = os.environ.get("LOCALAPPDATA", "")
    documents = os.path.join(os.environ.get("USERPROFILE", ""), "Documents")

    for base in [os.path.join(local, "WeChat"), os.path.join(local, "Tencent", "WeChat"),
                 os.path.join(documents, "WeChat Files")]:
        if os.path.isdir(base):
            for sub in ["Cache", "Video", "Image", "File", "Data"]:
                p = os.path.join(base, sub)
                if os.path.isdir(p):
                    sz = dir_total(p)
                    if sz > 0:
                        results.append(CacheItem(
                            path=p, size=sz, provider="app_cache",
                            label=f"WeChat {sub}", safety=SafetyLevel.SAFE,
                            extra={"type": "wechat"},
                        ))
    return results


def _scan_zoom(root: str) -> list[CacheItem]:
    results = []
    appdata = os.environ.get("APPDATA", "")
    local = os.environ.get("LOCALAPPDATA", "")

    for base in [os.path.join(appdata, "Zoom"), os.path.join(local, "Zoom")]:
        if os.path.isdir(base):
            for sub in ["cache", "data", "downloads", "logs", "Recording"]:
                p = os.path.join(base, sub)
                if os.path.isdir(p):
                    sz = dir_total(p)
                    if sz > 0:
                        results.append(CacheItem(
                            path=p, size=sz, provider="app_cache",
                            label=f"Zoom {sub}", safety=SafetyLevel.CAUTION,
                            extra={"type": "zoom"},
                        ))
    return results


def _scan_obsidian(root: str) -> list[CacheItem]:
    results = []
    appdata = os.environ.get("APPDATA", "")

    ob = os.path.join(appdata, "Obsidian")
    if os.path.isdir(ob):
        for sub in ["Cache", "GPUCache", "Local Storage"]:
            p = os.path.join(ob, sub)
            if os.path.isdir(p):
                sz = dir_total(p)
                if sz > 0:
                    results.append(CacheItem(
                        path=p, size=sz, provider="app_cache",
                        label=f"Obsidian {sub}", safety=SafetyLevel.SAFE,
                        extra={"type": "obsidian"},
                    ))
    return results


def _scan_vsstudio(root: str) -> list[CacheItem]:
    results = []
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")

    vs_paths = [
        os.path.join(local, "Microsoft", "VisualStudio", "ComponentModelCache"),
        os.path.join(appdata, "Microsoft", "VisualStudio", "Feedback"),
        os.path.join(local, "Microsoft", "VisualStudio", "ImageCache"),
    ]
    for p in vs_paths:
        if os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="app_cache",
                    label=f"VS Studio {os.path.basename(p)}",
                    safety=SafetyLevel.CAUTION,
                    extra={"type": "visual_studio"},
                ))
    return results


def _scan_spotify(root: str) -> list[CacheItem]:
    results = []
    local = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    paths = [
        os.path.join(local, "Spotify", "Storage"),
        os.path.join(local, "Spotify", "Data"),
        os.path.join(local, "Spotify", "BrowserCache"),
        os.path.join(appdata, "Spotify", "Cache"),
    ]
    for p in paths:
        if os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="app_cache",
                    label=f"Spotify {os.path.basename(p)}",
                    safety=SafetyLevel.SAFE,
                    extra={"type": "spotify", "rebuild_cost": "low"},
                ))
    return results


def _scan_whatsapp(root: str) -> list[CacheItem]:
    results = []
    local = os.environ.get("LOCALAPPDATA", "")
    p = os.path.join(local, "WhatsApp", "Cache")
    if os.path.isdir(p):
        sz = dir_total(p)
        if sz > 0:
            results.append(CacheItem(
                path=p, size=sz, provider="app_cache",
                label="WhatsApp Cache",
                safety=SafetyLevel.SAFE,
                extra={"type": "whatsapp", "rebuild_cost": "low"},
            ))
    return results


register("discord", _scan_discord)
register("slack", _scan_slack)
register("teams", _scan_teams)
register("wechat", _scan_wechat)
register("zoom", _scan_zoom)
register("obsidian", _scan_obsidian)
register("vsstudio", _scan_vsstudio)
register("spotify", _scan_spotify)
register("whatsapp", _scan_whatsapp)
