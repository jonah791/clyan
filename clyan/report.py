"""汇报层 — 给 AI 看的最终输出。

三层架构的最外层:
  扫描层 → 发现文件/目录（原始路径 + 大小）
  安全层 → 保护检查 + 等级 + 置信度 + 影响预测  
  汇报层 → 结构化输出 + MCP 序列化（本模块）

汇报层职责:
  1. 将 CacheItem 序列化为 AI 可读的 JSON
  2. 附加 enrich/confidence/impact 信号
  3. 按 recovery_cost 分组
  4. 生成总结 + 建议
"""

from typing import Any
from .utils.size import format_size
from .utils.scanner_base import _enrich
from .utils.confidence import compute_and_attach
from .utils.impact import attach_impact


def _enrich_items(items: list[dict]) -> None:
    """Apply safety layer signals to items list in-place.

    This is the bridge between scan layer (raw data) and report layer.
    Attaches: age_days, tool_installed, would_break, recovery_cost,
              ecosystem, confidence, reason.
    """
    for item in items:
        try:
            _enrich(item)
            attach_impact(item)
            compute_and_attach(item)
        except Exception:
            item.setdefault("confidence", 0.0)
            item.setdefault("reason", "")


def build_report(items: list[dict], path: str = "") -> dict:
    """Build structured report for AI from raw scan items.

    Args:
      items: List of item dicts (from CacheItem.to_dict())
      path: Scanned path (optional)

    Returns:
      Structured dict with items, summary, phases, recommendation.
    """
    # 1. Enrich with safety layer signals
    _enrich_items(items)

    # 2. Sort by recovery_cost, then size desc
    cost_order = {"none": 0, "low": 1, "medium": 2, "high": 3, "unknown": 4}
    items.sort(key=lambda i: (cost_order.get(i.get("recovery_cost", "unknown"), 99),
                              -i.get("size", 0)))

    # 3. Group into phases
    phases = []
    phase_items: dict[str, list[dict]] = {}
    for item in items:
        cost = item.get("recovery_cost", "unknown")
        phase_items.setdefault(cost, []).append(item)

    for cost in ["none", "low", "medium", "high", "unknown"]:
        pitems = phase_items.get(cost, [])
        if pitems:
            total = sum(i.get("size", 0) for i in pitems)
            # Ecosystem breakdown
            eco: dict[str, dict] = {}
            for i in pitems:
                e = i.get("ecosystem", "other")
                eco.setdefault(e, {"count": 0, "size": 0})
                eco[e]["count"] += 1
                eco[e]["size"] += i.get("size", 0)
            phases.append({
                "cost": cost,
                "item_count": len(pitems),
                "total_size": total,
                "total_size_human": format_size(total),
                "ecosystem_breakdown": [
                    {"ecosystem": k, "count": v["count"], "size_human": format_size(v["size"])}
                    for k, v in sorted(eco.items(), key=lambda x: -x[1]["size"])
                ],
            })

    total_size = sum(i.get("size", 0) for i in items)

    # 4. Recommendation
    rec = _recommend(phases, total_size)

    return {
        "path": path,
        "total_size": total_size,
        "total_size_human": format_size(total_size),
        "total_items": len(items),
        "phases": phases,
        "items": items[:100],  # Preview first 100
        "recommendation": rec,
    }


def _recommend(phases: list[dict], total_size: int) -> str:
    """Generate recommendation string."""
    parts = []
    parts.append(f"总计 {format_size(total_size)} ({total_size/1e9:.1f} GB)")
    for p in phases:
        c = p["cost"]
        s = p["total_size_human"]
        n = p["item_count"]
        eco = ", ".join(f"{e['ecosystem']}: {e['size_human']}" for e in p.get("ecosystem_breakdown", [])[:3])
        if c == "none":
            parts.append(f"Phase 1 (cost=none): {n}项 {s} [{eco}] — 零风险，立即执行")
        elif c == "low":
            parts.append(f"Phase 2 (cost=low): {n}项 {s} [{eco}] — 低风险")
        elif c == "medium":
            parts.append(f"Phase 3 (cost=medium): {n}项 {s} [{eco}] — 中风险")
        elif c == "high":
            parts.append(f"Phase 4 (cost=high): {n}项 {s} [{eco}] — 高风险")
    parts.append("建议: Phase 1→2→3→4 顺序执行")
    return " | ".join(parts)
