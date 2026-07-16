"""Tests for report.py: build_report + enrichment."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from clyan.report import build_report

def make_item(path, size, provider, age_days=60, confidence=85, safety="safe", extra_type=None):
    return {
        "path": path, "size": size, "provider": provider,
        "age_days": age_days, "confidence": confidence, "safety": safety,
        "extra": {"type": extra_type or provider},
    }

def test_empty():
    r = build_report([], "C:\\")
    assert r["total_items"] == 0
    assert r["total_size"] == 0
    assert len(r["phases"]) == 0
    print("  PASS test_empty")

def test_single():
    items = [make_item("C:\\cache\\npx", 1_400_000_000, "npm_deep", age_days=200)]
    r = build_report(items, "C:\\")
    assert r["total_items"] == 1
    assert r["total_size"] == 1_400_000_000
    assert "recommendation" in r
    print("  PASS test_single")

def test_enrich():
    from clyan.report import _enrich_items
    items = [make_item("C:\\test\\npm", 1_000_000, "npm_deep")]
    _enrich_items(items)
    item = items[0]
    assert "ecosystem" in item
    assert "recovery_cost" in item
    print(f"  PASS test_enrich (eco={item.get('ecosystem')})")

if __name__ == "__main__":
    test_empty()
    test_single()
    test_enrich()
    print("All report tests passed!")
