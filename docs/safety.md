# 安全体系文档

> Clyan 的安全体系设计原则: **不做内置决策，提供完整信号，由 AI 判断**。

## 三层安全等级

每个缓存/文件项被标记为三个等级之一:

| 等级 | 含义 | 示例 |
|------|------|------|
| 🟢 **SAFE** | 安全可删除，自动重建 | `node_modules/`, `.cache/`, `Temp/`, 浏览器缓存 |
| 🟡 **CAUTION** | 注意 — 可能需重装或重建 | `.venv/`, VS Code 扩展, `.dart_tool` |
| 🔴 **UNSAFE** | 不可删 — 含配置/凭据/数据 | `.ssh/`, `.git/`, `Desktop/`, 全局 npm |

### 判定规则

1. 路径从右向左匹配目录名
2. 匹配到 SAFE 或 CAUTION 目录名 → 返回对应等级
3. 无匹配 → UNSAFE（默认安全）

## 保护路径系统

31 条硬编码保护规则，覆盖系统关键目录:

| 类别 | 保护路径 | 深度 |
|------|---------|------|
| 系统根目录 | `C:\Windows`, `C:\Program Files`, `C:\ProgramData` | 全部 |
| 系统特殊 | `C:\$Recycle.Bin`, `C:\Boot`, `C:\Recovery` | 全部 |
| 用户配置 | `%USERPROFILE%\.ssh`, `.gnupg`, `.aws`, `.kube` | 全部 |
| VCS | `.git`, `.svn`, `.hg`（任何位置） | 全部 |
| 用户内容 | `Desktop`, `Documents`, `Pictures`, `Music`, `Videos` | 全部 |
| 包管理器 | `%APPDATA%\npm` | 全部 |

### 豁免规则

34 条豁免规则允许在保护路径内清理特定子目录:

| 豁免目录 | 例外（不豁免的场景） |
|---------|-------------------|
| `Temp`, `tmp`, `cache` | — |
| `node_modules` | 不在 `%APPDATA%\npm` 下 |
| `.venv`, `venv` | — |
| `target`, `build`, `dist` | 不在 `Program Files` 下 |
| `__pycache__`, `.mypy_cache`, `.pytest_cache` | — |
| `.next`, `.turbo`, `.gradle` | — |
| `Prefetch`, `FontCache` | 不在 `Windows` 下 |

## 信任系统（v0.14.0+）

AI 可以将特定路径标记为"信任"，绕过保护规则:

```bash
clyan trust add C:\Users\tr\AppData\Local\SomeApp --reason "AI verified safe"
clyan trust list
clyan trust remove C:\Users\tr\AppData\Local\SomeApp
```

### 工作原理

1. `is_protected()` 检查路径时先查信任表
2. 如果路径本身或任一祖先路径在信任表中 → 跳过保护规则
3. 信任记录持久化到 SQLite，跨会话有效

### 通用保护（v1.0.0-rc.3+）

所有 56 provider 在 `detect_all()` 中自动通过 `is_protected()` 过滤。
不再需要 provider 手动调用保护检查。

## ⚡ Reflex 安全机制（v1.0.0-rc+）

Reflex 是无意识的，但安全性由三层保证:

| 反射级别 | 安全机制 | 风险 |
|--------|---------|------|
| **tick** (`check_disk_pulse`) | 只读 statvfs + 缓存，不碰磁盘 | 零风险 |
| **twitch** (`auto_clear_safe`) | **只删 recovery_cost=none 的项** | 极低风险 |
| **spasm** (`reclaim --phase`) | 分阶段执行，每阶段可独立确认 | 中风险 |

### auto_clear_safe 的安全过滤

```
1. 全量扫描 → 获取所有 items
2. 过滤 recovery_cost == "none"  ← 只碰零成本项
3. 按 size 降序排列
4. 使用回收站 (send2trash)  ← 可还原
5. 执行后测量 actual_freed
6. 返回 protected_paths_skipped  ← 被保护的路径不删
```

cost=none 的典型项：Temp / npx 二进制 / 缩略图缓存 / WER 错误报告 / 最近文档。

## 置信度评分（v0.4.0+）

6 信号加权评分 + 行为学习调整, 0.0–1.0:

| 信号 | 权重 | 最高分 | 说明 |
|------|------|--------|------|
| 安全级别 | 30% | 30 | SAFE=30, CAUTION=15, UNSAFE=0 |
| 文件陈旧度 | 25% | 25 | >90天=25, >30天=17, >7天=8, 近期=0 |
| 工具已卸载 | 15% | 15 | 对应包管理器不在 PATH 中=15 |
| 已知缓存目录名 | 10% | 10 | npm-cache / Temp / __pycache__ 等 |
| 孤儿标记 | 10% | 10 | Temp 内孤儿临时目录 |
| **重建成本** | **10%** | **20** | **none=+20, low=+5, high=-20** |

### 行为学习调整（v1.0.0-rc+）

置信度分数再叠加行为学习:

| 条件 | 调整 | 原因 |
|------|------|------|
| AI 连续跳过某 provider (>70%) | **-0.10** | AI 认为不需要 |
| AI 连续清理某 provider (>70%) | **+0.05** | AI 认为安全 |
| 历史准确率 < 70% | **-0.05** | 校准 |
| 历史准确率 > 95% | **+0.03** | 信任 |
| 新类型 (<2 次出现) | **-0.03** | 保守 |

## 影响预测（v0.13.0+）

每个 item 自动附带影响预测字段:

```json
{
  "would_break": ["pip install would re-download all packages from PyPI"],
  "would_affect": ["pip", "python", "virtualenv"],
  "recovery_cost": "high",
  "ecosystem": "python"
}
```

### recovery_cost 含义

| 等级 | 含义 | 示例 |
|------|------|------|
| `none` | 无影响，自动重建 | Temp, 浏览器缓存, WER, npx |
| `low` | 本地快速重建 | IDE 缓存, 缩略图 |
| `medium` | 需要一些时间 | 构建产物, Flutter 缓存 |
| `high` | 需要网络下载 | pip/npm/cargo 缓存, ML 模型 |
| `unknown` | 无法判断 | 默认为未知 |

### 生态分组

11 个生态组, AI 可按组批量决策:

| 生态组 | Provider 示例 |
|--------|-------------|
| `node` | npm_cache, npm_deep, npm_prune, pnpm_cache, node_modules |
| `python` | pip_cache, pip_deep, python, venv |
| `rust` | cargo_registry, target |
| `go` | go_cache |
| `java` | gradle_cache, maven_cache |
| `dotnet` | nuget_cache |
| `browser` | browser, browser_deep |
| `ide` | vscode_cache, jetbrains_cache, ide |
| `windows` | system, winsxs, windows_installer, dism_cleanup, windows_extra |
| `ml` | ml_cache, docker_images |
| `game` | gpu_caches |
| `other` | small_files, vm_caches, windows_logs, empty_dirs |

## 历史准确率（v0.14.0+）

每次清理后记录每个 provider 的预计释放 vs 实际释放:

```json
{
  "historical_accuracy": {
    "clean_count": 3,
    "avg_accuracy": 0.91,
    "total_predicted": 10000000,
    "total_actual": 9100000
  }
}
```

AI 可以利用这个数据决定是否清理某类缓存:
- `avg_accuracy` ≥ 0.9 → 可信
- `avg_accuracy` < 0.7 → 不可信，谨慎

## 两阶段清理协议

AI 通过 `clean_propose` + `clean_confirm` 两步完成安全清理:

```
Phase 1: clean_propose(items)
  → 返回 action_id + 影响分析（不删东西）
Phase 2: clean_confirm(action_id)
  → 执行实际删除
  → 返回 actual_freed + protected_warned
```

对于受信任的 AI Agent，可直接使用 `clean_execute` 或 `auto_clear_safe`。

## protected_warned 机制

执行层不再硬拦截保护路径（v0.10.0+），改为:

1. 检测到保护路径 → 正常执行
2. 在返回结果中附加 `protected_warned` 列表
3. AI 自己决定是否继续
