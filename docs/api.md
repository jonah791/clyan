# MCP 工具参考

> Clyan 提供 19 个 MCP 工具，通过 stdio 传输协议供 AI Agent 调用。
> 启动: `clyan mcp`

## 扫描工具

### scan_quick

全量扫描，并行执行所有分类。AI 的"第一件事"。

```json
{
  "path": "C:\\Users\\tr"  // 根路径，默认当前用户
}
```

返回: 按分类聚合的可清理空间，含完整信号字段。

### scan_dev_garbage

开发者缓存/垃圾扫描（45 provider 并发，含 Winapp2 社区清理器）。

```json
{
  "path": "C:\\Users\\tr",
  "min_size_mb": 50  // 可选，过滤小于此值的项
}
```

返回: 每项附带 `would_break` / `ecosystem` / `recovery_cost` / `historical_accuracy`。

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

## 分析工具

### get_confidence_summary

给任意 items 列表附加置信度评分 + 影响预警。

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

返回:
```json
{
  "provider": "npm_cache",
  "history": [
    {"op_id": 5, "predicted_size": 3000000, "actual_freed": 2800000, "accuracy_ratio": 0.93}
  ],
  "summary": {
    "total_ops": 3,
    "avg_accuracy": 0.91,
    "total_predicted": 10000000,
    "total_actual": 9100000
  }
}
```

### system_health

系统健康检查。一次调用获取磁盘 + 可回收 + 趋势 + 准确率全貌。

```json
{
  "path": "C:\\"
}
```

## 清理工具

### clean_propose（阶段 1/2）

安全清理两阶段协议的第一阶段：提交 items，返回 action_id + 影响分析。**不执行删除。**

```json
{
  "items": [...],
  "fast": false
}
```

返回 `action_id`（有效期内的令牌），AI 可以展示影响给用户确认。

### clean_confirm（阶段 2/2）

用 `action_id` 确认执行。只有被确认的才会真正删除。

```json
{
  "action_id": "abc12345"
}
```

返回: `success_count` / `fail_count` / `actual_freed` / `protected_warned`。

### clean_auto

一键自主清理：scan → 评分 → 过滤 → 执行。

```json
{
  "path": "C:\\Users\\tr",
  "strategy": "safe",        // safe / aged / orphan / all
  "min_confidence": 0.9,
  "use_trash": true,
  "fast": false
}
```

### clean_deep

完整清理周期：全量扫描 → 评分 → 过滤 → 执行 → 验证。比 clean_auto 更全面。

```json
{
  "path": "C:\\Users\\tr",
  "strategy": "safe",
  "use_trash": true,
  "fast": false
}
```

### clean_plan

分析 items 返回按 `recovery_cost` 排序的执行计划。AI 先看计划再决定怎么删。

```json
{
  "items": [...]
}
```

返回:
```json
{
  "total_items": 100,
  "phases": [
    {"cost": "none", "count": 30, "total_size_human": "1.2 GB"},
    {"cost": "low", "count": 20, "total_size_human": "500 MB"},
    {"cost": "medium", "count": 40, "total_size_human": "2.1 GB"},
    {"cost": "high", "count": 10, "total_size_human": "3.4 GB"}
  ],
  "recommendation": "Execute phases in order: start with 'none' cost items..."
}
```

### clean_preview

预览检查（保护路径警告、已存在检查）。不删东西。

```json
{
  "items": [...]
}
```

### clean_execute

⚠ 立即执行删除。AI 指定每项的 `method`（trash / direct / native / auto）。

```json
{
  "items": [
    {
      "path": "C:\\cache\\npm",
      "size": 1000000,
      "provider": "npm_cache",
      "method": "trash"  // AI 指定删除方法
    }
  ],
  "fast": false
}
```

## 历史 / 管理工具

### history

查看清理历史。

```json
{
  "op_id": null,   // 可选，指定查看某次操作
  "limit": 20
}
```

### undo

撤销某次清理（标记为已撤销）。

```json
{
  "op_id": 5
}
```

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
| `confidence` | float | 置信度 0.0–1.0 |
| `reason` | string | 中文评分原因 |
| `would_break` | string[] | 删除后果描述 |
| `would_affect` | string[] | 受影响的应用 |
| `recovery_cost` | string | none / low / medium / high |
| `ecosystem` | string | node / python / windows / browser / ide / ml / build |
| `age_days` | int | 最近修改距今天数 |
| `tool_installed` | bool | 对应工具是否仍在系统中 |
| `historical_accuracy` | object | 该 provider 的历史清理准确率（如有） |
| `warning` | string | 影响预警（如有） |
