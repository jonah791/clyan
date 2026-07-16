from ..utils.paths import browser_cache_paths
import os
import time
import glob
from ..utils.scanner_base import ScanResult, BaseScanner
from ..utils.dirtree import dir_total
from ..core.config import DangerLevel
from .providers import CacheItem


class BrowserCacheScanner(BaseScanner):
    def __init__(self):
        self.paths = browser_cache_paths()

    def scan(self) -> ScanResult:
        result = ScanResult()
        start = time.time()

        browsers = [
            ("chrome", "Chrome Browser Cache"),
            ("chrome_code_cache", "Chrome Code Cache"),
            ("edge", "Edge Browser Cache"),
            ("edge_code_cache", "Edge Code Cache"),
        ]

        for key, label in browsers:
            p = self.paths.get(key, "")
            if p and os.path.isdir(p):
                try:
                    sz = dir_total(p)
                    if sz > 0:
                        item = CacheItem(
                            path=p, size=sz, provider="browser",
                            label=label, safety=DangerLevel.SAFE,
                            extra={"browser": label.split()[0]},
                        )
                        result.items.append(item.to_dict())
                        result.total_size += sz
                except Exception:
                    result.errors.append(f"error scanning {label}: {p}")

        firefox_dir = self.paths.get("firefox", "")
        if firefox_dir and os.path.isdir(firefox_dir):
            for profile in glob.glob(os.path.join(firefox_dir, "*.default*", "cache2")):
                if os.path.isdir(profile):
                    try:
                        sz = dir_total(profile)
                        if sz > 0:
                            item = CacheItem(
                                path=profile, size=sz, provider="browser",
                                label="Firefox Cache", safety=DangerLevel.SAFE,
                                extra={"browser": "Firefox"},
                            )
                            result.items.append(item.to_dict())
                            result.total_size += sz
                    except Exception:
                        result.errors.append(f"error scanning Firefox: {profile}")

        result.items.sort(key=lambda x: x["size"], reverse=True)
        result.item_count = len(result.items)
        result.scan_time_ms = (time.time() - start) * 1000
        return result
