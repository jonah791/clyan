import os
import time
import glob
from ..utils.scanner_base import ScanResult, BaseScanner
from ..utils.size import format_size


def _dir_total(path):
    total = 0
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        total += e.stat().st_size
                    elif e.is_dir(follow_symlinks=False):
                        total += _dir_total(e.path)
                except Exception:
                    pass
    except Exception:
        pass
    return total


def _scan_conda():
    items = []
    for conda_root in (
        os.environ.get("CONDA_ROOT", ""),
        r"C:\ProgramData\miniconda3",
        os.path.join(os.environ.get("USERPROFILE", ""), "miniconda3"),
        os.path.join(os.environ.get("USERPROFILE", ""), "anaconda3"),
    ):
        if not conda_root or not os.path.isdir(conda_root):
            continue
        base_size = _dir_total(conda_root)
        items.append({
            "name": "miniconda3 (base)",
            "path": conda_root,
            "type": "conda",
            "size": base_size,
            "size_human": format_size(base_size),
            "safety": "unsafe",
        })
        envs_dir = os.path.join(conda_root, "envs")
        if os.path.isdir(envs_dir):
            for env in sorted(os.listdir(envs_dir)):
                env_path = os.path.join(envs_dir, env)
                if os.path.isdir(env_path):
                    sz = _dir_total(env_path)
                    if sz > 10 * 1024 * 1024:
                        items.append({
                            "name": f"conda env: {env}",
                            "path": env_path,
                            "type": "conda_env",
                            "size": sz,
                            "size_human": format_size(sz),
                            "safety": "caution",
                        })
        break
    return items


def _scan_scoop():
    items = []
    scoop_dir = os.path.join(os.environ.get("USERPROFILE", ""), "scoop")
    if not os.path.isdir(scoop_dir):
        return items
    apps_dir = os.path.join(scoop_dir, "apps")
    if os.path.isdir(apps_dir):
        for app in sorted(os.listdir(apps_dir)):
            app_path = os.path.join(apps_dir, app)
            if os.path.isdir(app_path):
                sz = _dir_total(app_path)
                if sz > 10 * 1024 * 1024:
                    items.append({
                        "name": f"scoop: {app}",
                        "path": app_path,
                        "type": "scoop_app",
                        "size": sz,
                        "size_human": format_size(sz),
                        "safety": "unsafe",
                    })
    return items


def _scan_cargo():
    items = []
    cargo_root = os.path.join(os.environ.get("USERPROFILE", ""), ".cargo")
    if not os.path.isdir(cargo_root):
        return items
    bin_dir = os.path.join(cargo_root, "bin")
    if os.path.isdir(bin_dir):
        sz = _dir_total(bin_dir)
        if sz > 0:
            items.append({
                "name": "cargo installed binaries",
                "path": bin_dir,
                "type": "cargo_bin",
                "size": sz,
                "size_human": format_size(sz),
                "safety": "unsafe",
            })
    registry = os.path.join(cargo_root, "registry")
    if os.path.isdir(registry):
        sz = _dir_total(registry)
        if sz > 10 * 1024 * 1024:
            items.append({
                "name": "cargo registry (crates + index)",
                "path": registry,
                "type": "cargo_registry",
                "size": sz,
                "size_human": format_size(sz),
                "safety": "caution",
            })
    return items


def _scan_go():
    items = []
    go_root = os.path.join(os.environ.get("USERPROFILE", ""), "go")
    if not os.path.isdir(go_root):
        return items
    go_bin = os.path.join(go_root, "bin")
    if os.path.isdir(go_bin):
        sz = _dir_total(go_bin)
        if sz > 0:
            items.append({
                "name": "go installed binaries",
                "path": go_bin,
                "type": "go_bin",
                "size": sz,
                "size_human": format_size(sz),
                "safety": "unsafe",
            })
    pkg = os.path.join(go_root, "pkg")
    if os.path.isdir(pkg):
        sz = _dir_total(pkg)
        if sz > 10 * 1024 * 1024:
            items.append({
                "name": "go module cache",
                "path": pkg,
                "type": "go_cache",
                "size": sz,
                "size_human": format_size(sz),
                "safety": "caution",
            })
    return items


def _scan_npm_global():
    items = []
    appdata = os.environ.get("APPDATA", "")
    npm_global = os.path.join(appdata, "npm", "node_modules")
    if os.path.isdir(npm_global):
        sz = _dir_total(npm_global)
        if sz > 10 * 1024 * 1024:
            items.append({
                "name": "npm global packages",
                "path": npm_global,
                "type": "npm_global",
                "size": sz,
                "size_human": format_size(sz),
                "safety": "unsafe",
            })
    return items


class PackagesScanner(BaseScanner):
    def __init__(self):
        self.root = os.environ.get("USERPROFILE", "C:\\")

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        scanners = [
            ("conda", _scan_conda),
            ("scoop", _scan_scoop),
            ("cargo", _scan_cargo),
            ("go", _scan_go),
            ("npm_global", _scan_npm_global),
        ]

        all_items = []
        for name, fn in scanners:
            try:
                items = fn()
                all_items.extend(items)
            except Exception as e:
                result.errors.append(f"{name}: {e}")

        all_items.sort(key=lambda x: x["size"], reverse=True)
        total = sum(i["size"] for i in all_items)

        result.items = all_items
        result.total_size = total
        result.item_count = len(all_items)
        result.extra = {
            "providers_scanned": [name for name, _ in scanners],
        }
        result.scan_time_ms = (time.time() - start) * 1000
        return result
