# MCP 工具参考

> Clyan 提供 23 个 MCP 工具 + 1 个 Resource，通过 stdio 传输协议供 AI Agent 调用。
> 启动: `clyan mcp`

## ⚡ Reflex 工具

### check_disk_pulse

**磁盘健康检查。** <1ms，零扫描零 IO。使用缓存的状态 + statvfs。

```json
{
  "path": "C:\\"
}
```

返回:
```json
{
  "status": "healthy",        // healthy / warning / critical
  "free_gb": 127.1,
  "free_pct": 29.1,
  "safe_reclaimable_gb": 28.4,
  "days_until_critical": 47,
  "growth_rate_gb_per_week": 1.8,
  "cached": true,
  "ellapsed_ms": 0.5
}
```

如果缓存为空，自动执行轻量预热（<200ms）。

### auto_clear_safe

**零决策自动清理。** 只删 recovery_cost=none 的项（Temp / npx / 缩略图 / WER 等）。
使用缓存数据优先，避免重复全量扫描。

```json
{
  "path": "C:\\Users\\tr",
  "target_gb": 5.0
}
```

返回:
```json
{
  "reclaimed_gb": 4.2,
  "items_cleared": 12,
  "items_failed": 0,
  "actual_freed_human": "4.15 GB",
  "ellapsed_ms": 1230
}
```

### reclaim

**全量扫描 → 去重 → enrich → 分 5 阶段 → 执行。一次性回收计划。**

```json
{
  "path": "C:\\Users\\tr",
  "phase": "",        // 可选: 指定执行某阶段 (none/low/medium/high)
  "dry_run": false    // 可选: 只预览不执行
}
```

返回 phases 数组:
```json
{
  "total_size": 1040618848,
  "total_size_human": "992.41 MB",
  "total_items": 364,
  "phases": [
    {
      "cost": "none",
      "item_count": 39,
      "total_size_human": "28.97 GB",
      "ecosystem_breakdown": [...],
      "items": [...]
    },
    {
      "cost": "low",
      "item_count": 13,
      "total_size_human": "1.12 GB",
      ...
    }
  ],
  "recommendation": "按 Phase 1→2→3→4 顺序执行..."
}
```

## 🔍 扫描工具

### scan_quick

全量扫描，并行执行所有分类。AI 的"第一件事"。

```json
{
  "path": "C:\\Users\\tr"
}
```

返回: 按分类聚合的可清理空间（53 provider + Winapp2 并行）。

### scan_dev_garbage

开发者缓存/垃圾扫描（53 provider 并发，含 Winapp2 社区清理器）。

```json
{
  "path": "C:\\Users\\tr",
  "min_size_mb": 50
}
```

### scan_browsers

浏览器缓存扫描（Chrome/Edge/Firefox 等）。

### scan_system

Windows 系统临时文件 + Temp 深度分解 + 回收站。

### scan_duplicates

重复文件检测。三步流水线：大小分组 → 4KB 部分哈希 → 全量哈希。

```json
{
  "path": "C:\\Users\\tr"
}
```

### scan_disk

磁盘概览：总容量 / 已用 / 剩余 / 目录树 / 分类占用 / 可回收垃圾。

```json
{
  "path": "C:\\",
  "depth": 2
}
```

### scan_packages

已安装的包管理器环境检测（npm / pip / cargo / go / conda / scoop 等）。

## 🧠 分析工具

### get_confidence_summary

给任意 items 列表附加置信度评分 + 影响预警 + 行为学习调整。

```json
{
  "items": [
    {"path": "C:\\cache\\npm", "size": 1000000, "safety": "safe", "provider": "npm_cache"}
  ]
}
```

### get_provider_feedback

查询某个 provider 的历史清理准确率。用于辅助 AI 决策。

```json
{
  "provider": "npm_cache"
}
```

### system_health

系统健康检查。一次调用获取磁盘 + 可回收 + 趋势 + 准确率全貌。

```json
{
  "path": "C:\\"
}
```

### clean_plan

分析 items 返回按 `recovery_cost` 排序的执行计划。

```json
{
  "items": [...]
}
```

## 🧹 清理工具

### clean_propose（阶段 1/2）

安全清理两阶段协议的第一阶段：提交 items，返回 action_id + 影响分析。

```json
{
  "items": [...],
  "fast": false
}
```

### clean_confirm（阶段 2/2）

用 `action_id` 确认执行。

```json
{
  "action_id": "abc12345"
}
```

### clean_auto

一键自主清理：scan → 评分 → 过滤 → 执行。

### clean_deep

完整清理周期：全量扫描 → 评分 → 过滤 → 执行 → 验证。

### clean_preview

预览检查（保护路径警告）。

### clean_execute

⚠ 立即执行删除。AI 指定每项的 `method`（trash / direct / native / auto）。

```json
{
  "items": [
    {"path": "C:\\cache\\npm", "size": 1000000, "method": "trash"}
  ]
}
```

## 📜 历史工具

### history

查看清理历史。

```json
{
  "op_id": null,
  "limit": 20
}
```

### undo

撤销某次清理。

```json
{
  "op_id": 5
}
```

## 🔗 Resource

### disk://C:/health

MCP Resource 端点。AI Agent 可订阅此资源，获取 C 盘实时健康状态。

## MCP 工具信号字段

每个扫描返回的 item 包含以下信号供 AI 决策：

| 字段 | 类型 | 说明 |
|------|------|------|
| `path` | string | 完整路径 |
| `size` | int | 字节大小 |
| `size_human` | string | 人类可读大小 |
| `provider` | string | provider 名称（npm_cache / winapp2 / python 等） |
| `label` | string | 人类可读标签 |
| `safety` | string | safe / caution / unsafe |
| `confidence` | float | 置信度 0.0–1.0（含行为学习调整） |
| `reason` | string | 中文评分原因 |
| `would_break` | string[] | 删除后果描述 |
| `would_affect` | string[] | 受影响的应用 |
| `recovery_cost` | string | none / low / medium / high |
| `ecosystem` | string | node / python / windows / browser / ide / ml |
| `age_days` | int | 最近修改距今天数 |
| `tool_installed` | bool | 对应工具是否仍在系统中 |
| `historical_accuracy` | object | 该 provider 的历史清理准确率（如有） |
| `_scanner` | string | 来源扫描器（仅 reclaim 用） |
