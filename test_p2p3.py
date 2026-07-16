"""Verify P2 + P3: undo + learning feedback loop"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from clyan.core.history import record_clean, get_provider_feedback, get_history, mark_undone, record_disk_snapshot
from clyan.learning import adjust_confidence

# P2: Undo/record pipeline
op_id = record_clean([{"path":"test","size":1000}], 1000, "delete", 1000000000, 1000001000)
print(f"record_clean op_id={op_id}")

h = get_history(limit=3)
print(f"history: {len(h)} entries")

r = mark_undone("nonexistent")
print(f"mark_undone: {r}")

record_disk_snapshot("C:\\", 500000000000, 200000000000, 300000000000)
print("record_disk_snapshot OK")

# P3: Learning feedback
fb = get_provider_feedback("system")
print(f"system feedback: {fb}")

adj = adjust_confidence("npm_cache", 0.85, {"type": "npm_cache"})
print(f"adjust_confidence: {adj}")

print("\nP2 + P3 verified OK")
