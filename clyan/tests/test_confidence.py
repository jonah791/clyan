"""Tests for confidence.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from clyan.utils.confidence import compute_and_attach

def test_old_safe():
    item = {"path": "C:\\test\\cache", "size": 1_000_000, "provider": "npm_cache",
            "safety": "safe", "extra": {"type": "npm_cache"}, "age_days": 200}
    compute_and_attach(item)
    assert "confidence" in item
    assert item["confidence"] >= 0.3
    print(f"  PASS test_old_safe (conf={item['confidence']})")

def test_new():
    item = {"path": "C:\\test\\cache", "size": 1_000_000, "provider": "browser",
            "safety": "safe", "extra": {"type": "browser_cache"}, "age_days": 5}
    compute_and_attach(item)
    assert "confidence" in item
    print(f"  PASS test_new (conf={item['confidence']})")

if __name__ == "__main__":
    test_old_safe()
    test_new()
    print("All confidence tests passed!")
