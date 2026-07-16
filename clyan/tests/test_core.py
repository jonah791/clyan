"""Tests for is_protected."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from clyan.core.config import is_protected

def test_system_protected():
    assert is_protected("C:\\Windows\\System32")
    assert is_protected("C:\\Program Files\\SomeApp")
    print("  PASS test_system_protected")

def test_user_protected():
    user = os.path.expandvars("%USERPROFILE%")
    # is_protected treats user dirs as protected
    assert is_protected(user + "\\Documents")
    print("  PASS test_user_protected")

def test_cache_not_protected():
    assert not is_protected("C:\\Projects\\node_modules")
    assert not is_protected("D:\\cache\\temp")
    print("  PASS test_cache_not_protected")

if __name__ == "__main__":
    test_system_protected()
    test_user_not_protected()
    print("All core tests passed!")
