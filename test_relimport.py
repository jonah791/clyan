"""Test relative import inside thread from disk_summary context."""
import os, sys
sys.path.insert(0, ".")
os.chdir("clyan")  # Go to the package dir

from concurrent.futures import ThreadPoolExecutor
import importlib

# This is what _walk_one does internally — test it
def test_classify_in_thread():
    from scan.disk_summary import _full_scan_one_pass
    print("Import from thread: OK")
    return True

with ThreadPoolExecutor() as pool:
    f = pool.submit(test_classify_in_thread)
    print(f"Result: {f.result()}")
