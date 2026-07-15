"""行为学习 — 根据 AI 的决策历史动态调整置信度。

原理: AI 的历史行为是最好的训练数据。
  - 如果 AI 连续 3 次拒绝清理某类缓存 → 降低置信度（AI 认为不需要）
  - 如果 AI 连续 3 次清理某类缓存 → 提高置信度（AI 认为安全）
  - 每次清理后记录 feedback → 实际释放 vs 预测释放 → 校准预测
"""

import os
import json
from typing import Any
from .core.history import get_provider_feedback, get_history


_LEARNING_CACHE: dict | None = None


def _load_learning() -> dict:
    """Load learning state from history + feedback."""
    global _LEARNING_CACHE
    if _LEARNING_CACHE is not None:
        return _LEARNING_CACHE

    learning: dict[str, Any] = {
        "provider_patterns": {},
        "provider_accuracy": {},
        "preferred_strategies": {},
    }

    # Collect provider patterns from history
    try:
        history = get_history(limit=50)
        for op in history:
            # items are stored as JSON string in items_json
            raw = op.get("items_json", "[]")
            if isinstance(raw, str):
                try:
                    items = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    items = []
            elif isinstance(raw, list):
                items = raw
            else:
                items = []
            # Also try 'results' and 'items' keys for MCP-based records
            if not items:
                items = op.get("results", op.get("items", []))
            for item in items:
                prov = item.get("provider", "unknown")
                if prov not in learning["provider_patterns"]:
                    learning["provider_patterns"][prov] = {
                        "total_in_history": 0,
                        "cleaned_in_history": 0,
                        "skipped_in_history": 0,
                    }
                pattern = learning["provider_patterns"][prov]
                pattern["total_in_history"] += 1
                # Count as cleaned if operation was successful
                if op.get("success_count", 0) > 0:
                    pattern["cleaned_in_history"] += 1
                # Items that were not cleaned
                pattern["skipped_in_history"] = (
                    pattern["total_in_history"] - pattern["cleaned_in_history"]
                )
    except Exception:
        pass

    # Collect provider accuracy
    try:
        for prov in ["npm_cache", "pip_cache", "browser", "system",
                      "python", "rust", "go", "ide", "winapp2"]:
            feedback = get_provider_feedback(prov, limit=5)
            if feedback:
                accuracies = [f.get("accuracy_ratio", 1.0) for f in feedback]
                learning["provider_accuracy"][prov] = {
                    "avg_accuracy": sum(accuracies) / len(accuracies),
                    "sample_count": len(accuracies),
                }
    except Exception:
        pass

    _LEARNING_CACHE = learning
    return learning


def adjust_confidence(provider: str, base_confidence: float,
                      extra: dict | None = None) -> float:
    """Adjust confidence based on behavioral learning.

    Returns adjusted confidence (0.0–1.0).
    The adjustment is additive: +0.05 to -0.15
    """
    learning = _load_learning()
    pattern = learning.get("provider_patterns", {}).get(provider, {})
    accuracy = learning.get("provider_accuracy", {}).get(provider, {})

    adjustment = 0.0

    # 1. If AI has consistently skipped this provider → lower confidence
    total = pattern.get("total_in_history", 0)
    cleaned = pattern.get("cleaned_in_history", 0)
    if total >= 3:
        skip_rate = 1.0 - (cleaned / total)
        if skip_rate > 0.7:  # AI skipped >70% of the time
            adjustment -= 0.10  # AI apparently doesn't want this → lower confidence
        elif skip_rate < 0.3:  # AI cleaned >70% of the time
            adjustment += 0.05  # AI trusts this → raise confidence

    # 2. Historical accuracy calibration
    avg_acc = accuracy.get("avg_accuracy")
    if avg_acc is not None:
        if avg_acc < 0.7:
            adjustment -= 0.05  # Over-predicting → lower confidence
        elif avg_acc > 0.95:
            adjustment += 0.03  # Under-predicting → slight boost

    # 3. Extra signals from item
    if extra:
        ctype = extra.get("type", "")
        # If AI has never cleaned this subtype before → be conservative
        type_pattern = pattern
        if type_pattern.get("total_in_history", 0) < 2:
            adjustment -= 0.03  # Unknown territory

    return max(0.0, min(1.0, base_confidence + adjustment))
