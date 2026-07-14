import os
import glob
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total





def _scan_nuget(root: str) -> list[CacheItem]:
    results = []
    userprofile = os.environ.get("USERPROFILE", "")
    local_appdata = os.environ.get("LOCALAPPDATA", "")

    for p, label in [
        (os.path.join(userprofile, ".nuget", "packages"), "NuGet global packages"),
        (os.path.join(local_appdata, "NuGet", "v3-cache"), "NuGet HTTP cache"),
        (os.path.join(local_appdata, "NuGet", "plugins-cache"), "NuGet plugins cache"),
    ]:
        if os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="nuget",
                    label=label, safety=SafetyLevel.SAFE,
                    extra={"type": "nuget"},
                ))
    return results


def _scan_go(root: str) -> list[CacheItem]:
    results = []
    userprofile = os.environ.get("USERPROFILE", "")
    for p, label in [
        (os.path.join(userprofile, "go", "pkg", "mod"), "Go module cache"),
        (os.path.join(userprofile, "go", "pkg", "mod", "cache"), "Go build cache"),
    ]:
        if os.path.isdir(p):
            sz = dir_total(p)
            if sz > 0:
                results.append(CacheItem(
                    path=p, size=sz, provider="go",
                    label=label, safety=SafetyLevel.SAFE,
                    extra={"type": "go_cache"},
                ))
    return results


def _scan_android(root: str) -> list[CacheItem]:
    results = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    sdk_path = os.environ.get("ANDROID_HOME", "")

    for p in glob.glob(os.path.join(local_appdata, "Google", "AndroidStudio*")):
        for sub in ["caches", "index", "tmp", "log"]:
            sp = os.path.join(p, "system", sub) if sub != "caches" else os.path.join(p, "caches")
            if os.path.isdir(sp):
                sz = dir_total(sp)
                if sz > 0:
                    results.append(CacheItem(
                        path=sp, size=sz, provider="android",
                        label=f"Android Studio {sub}",
                        safety=SafetyLevel.CAUTION,
                        extra={"type": "android_studio"},
                    ))

    if sdk_path:
        temp_dir = os.path.join(sdk_path, ".temp")
        if os.path.isdir(temp_dir):
            sz = dir_total(temp_dir)
            if sz > 0:
                results.append(CacheItem(
                    path=temp_dir, size=sz, provider="android",
                    label="Android SDK temp", safety=SafetyLevel.SAFE,
                    extra={"type": "android_sdk_temp"},
                ))
    return results


def _scan_flutter_cache(root: str) -> list[CacheItem]:
    results = []
    userprofile = os.environ.get("USERPROFILE", "")
    flutter_cache = os.path.join(userprofile, ".pub-cache")
    if os.path.isdir(flutter_cache):
        sz = dir_total(flutter_cache)
        if sz > 0:
            results.append(CacheItem(
                path=flutter_cache, size=sz, provider="flutter",
                label="Flutter/Dart pub cache", safety=SafetyLevel.SAFE,
                extra={"type": "pub_cache"},
            ))
    return results


def _scan_docker(root: str) -> list[CacheItem]:
    userprofile = os.environ.get("USERPROFILE", "")
    docker_dir = os.path.join(userprofile, "AppData", "Local", "Docker")
    if os.path.isdir(docker_dir):
        sz = dir_total(docker_dir)
        if sz > 0:
            return [CacheItem(
                path=docker_dir, size=sz, provider="docker",
                label="Docker (images + cache)",
                safety=SafetyLevel.CAUTION,
                extra={"type": "docker"},
            )]
    return []


register("nuget", _scan_nuget)
register("go", _scan_go)
register("android", _scan_android)
register("flutter", _scan_flutter_cache)
register("docker", _scan_docker)
