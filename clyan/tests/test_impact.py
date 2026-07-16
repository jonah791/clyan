"""Tests for impact.py: ecosystem_for + impact_for."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from clyan.utils.impact import ecosystem_for, impact_for

def test_ecosystem():
    cases = [
        ("npm_cache", "node"), ("npm_deep", "node"),
        ("pip_cache", "python"),
        ("winsxs", "windows"), ("discord", "app"),
        ("spotify", "app"), ("ide", "ide"),
    ]
    for provider, expected in cases:
        eco = ecosystem_for(provider)
        assert eco == expected, f"{provider}: expected {expected}, got {eco}"
    print(f"  PASS test_ecosystem ({len(cases)} cases)")

def test_all_have_impact():
    from clyan.scan.providers import _registry
    from clyan.utils.impact import _IMPACT_DB
    missing = [n for n in _registry if n not in _IMPACT_DB]
    assert not missing, f"Missing impact entries: {missing}"
    print(f"  PASS test_all_have_impact ({len(_registry)} providers)")

if __name__ == "__main__":
    test_ecosystem()
    test_all_have_impact()
    print("All impact tests passed!")
