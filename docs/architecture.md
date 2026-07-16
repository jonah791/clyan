# Clyan 架构文档

> 版本 1.0.0-rc.2 · 自用非商用开源项目

## 设计理念

Clyan 的核心原则：**工具做"全"和"准"，AI 做"判断"和"决策"**。

```
扫描层 → 全面发现 + 全量信号（不过滤、不设阈值）
执行层 → 安全执行 + 报告副作用（不硬拦截、不替 AI 选策略）
Reflex → 无意识反射（tick <1ms / twitch ~1s / spasm ~30s）
AI     → 分析信号 + 做判断 + 选删除方法（trash/direct/native）
```

### 与其他工具的本质区别

| 方面 | 传统工具 (BleachBit/Czkawka) | Clyan |
|------|------------------------------|-------|
| 目标用户 | 人类 | AI Agent |
| 交互方式 | GUI/TUI | MCP 协议 + CLI + Reflex |
| 决策者 | 用户手动选 | AI 分析信号后决策 |
| 安全模型 | 硬编码保护路径 | 保护路径 + AI 信任豁免 + 行为学习 |
| 学习能力 | 无 | 持久化历史 + 准确率 + **行为动态调整** |
| 主动能力 | 用户发现问题才启动 | **反射弧自动响应磁盘压力** |

## 系统架构

```
┌──────────────────────────────────────────────────┐
│                    CLI (cli.py)                   │
│   reclaim / pulse / auto-clear / scan / clean     │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│           MCP Server (23 tools + Resource)         │
│  check_disk_pulse / auto_clear_safe / reclaim     │
│  scan_* / clean_* / system_health / disk://       │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│                 Reflex Layer (reflex.py)           │
├──────────────────────────────────────────────────┤
│  check_pulse()          <1ms  statvfs + 缓存      │
│  auto_clear_safe()      ~1s  只删 cost=none 项    │
│  _lightweight_estimate() <200ms 自动预热          │
│  _refresh_pulse_cache() 扫描后自动更新             │
│  disk_pulse.json         1h TTL 状态缓存          │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│                 Reclaim (reclaim.py)               │
├──────────────────────────────────────────────────┤
│  全量扫描 → 去重 → enrich → 分5阶段 → 执行       │
│  输出 phases / ecosystem_breakdown / recommedation │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│                   Scan Pipeline                    │
├──────────────────┬───────────────────────────────┤
│  fast_scan       │  providers.detect_all()        │
│  (目录模式匹配)   │  (55 注册 provider)            │
│  50+ 构建目录    │  ┌─────────────────────────┐   │
│  match-and-stop  │  │ 内置 36 + 深度 17 个     │   │
│                  │  │ Winapp2 动态加载 3377     │   │
│                  │  └─────────────────────────┘   │
├──────────────────┴───────────────────────────────┤
│              ScanResult.to_dict()                  │
│  → _enrich / attach_impact / compute_and_attach   │
│  → _get_provider_accuracy                         │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│                Execution Pipeline                  │
├──────────────────────────────────────────────────┤
│  delete_items(items, use_trash, fast)             │
│  → 逐项 method: trash / direct / native / auto    │
│  → before/after free space 测量                   │
│  → 返回 actual_freed / delta / protected_warned   │
│  → record_clean + clean_feedback                  │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│              Learning Layer (learning.py)          │
├──────────────────────────────────────────────────┤
│  provider_patterns: AI 历史决策频率               │
│  provider_accuracy: 清理准确率校准                 │
│  adjust_confidence(): 动态调置信度 ±0.03~0.10     │
└──────────────────────────────────────────────────┘
```

## 数据流

### 扫描流程

1. CLI/MCP 收到扫描请求
2. 并行执行扫描器 + provider
3. 结果汇聚到 `ScanResult`
4. `to_dict()` 时逐项 enrich + impact + confidence + accuracy
5. `_refresh_pulse_cache()` 更新反射缓存
6. 返回结构化 JSON

### Reflex 流程

```
AI 即将下载大文件
  → 潜意识调用 check_disk_pulse (<1ms)
  ├  status=healthy → 无操作，继续下载
  └  status=warning → 自动调用 auto_clear_safe
                       ├ 缓存命中 → ~1s 执行
                       └ 缓存过期 → ~15s 扫描+执行
                       → 释放空间 → 继续下载
```

### Reclaim 流程

```
clyan reclaim C:\
  → DevGarbageScanner 扫描 → 342 项
  → SystemScanner 扫描     → 4 项
  → BrowserCacheScanner    → 2 项
  → 去重（按 path 去重）    → 348 项
  → enrich → compute_and_attach
  → 按 recovery_cost 排序分 5 阶段
  → 输出 phases + ecosystem_breakdown
```

## 模块结构

```
clyan/
├── __init__.py          # 版本号
├── __main__.py          # python -m clyan 入口
├── cli.py               # CLI 解析 + 命令分发
├── mcp_server.py        # MCP 服务器（23 工具 + Resource）
├── reflex.py            # ⚡ 反射弧：脉冲缓存 + auto_clear_safe
├── reclaim.py           # 📋 统一回收计划：全量→去重→分阶段
├── learning.py          # 🧠 行为学习：动态置信度调整
│
├── core/
│   ├── config.py        # 保护路径 / 豁免规则 / DangerLevel
│   └── history.py       # SQLite 历史 + 反馈 + 信任 + Winapp2 表
│
├── scan/
│   ├── space.py         # 目录空间分析
│   ├── dev_garbage.py   # 开发者垃圾（fast_scan + providers）
│   ├── system.py        # Windows 临时文件
│   ├── browser_cache.py # 浏览器缓存
│   ├── duplicates.py    # 重复文件（4KB hash + 并行 + inode 去重）
│   ├── large_files.py   # 大文件发现
│   ├── fast_scanner.py  # 目录模式匹配引擎
│   ├── disk_summary.py  # 磁盘概览 + 趋势
│   ├── node_waste.py    # node_modules 内部瘦身
│   ├── browser_deep.py  # Chrome/Edge/Firefox SQLite 深度清理
│   ├── packages.py      # 包管理器环境检测
│   └── providers/       # 53 provider
│       ├── __init__.py  # CacheItem / register / detect_all (47+)
│       ├── node.py / python_prov.py / rust_prov.py / ...
│       ├── npm_deep.py / pip_deep.py / npm_prune.py    # 深度裁剪
│       ├── windows_installer.py / dism_cleanup.py       # 系统扩展
│       ├── winapp2_prov.py  # 动态加载 3377 社区清理器
│       └── ...
│
├── clean/
│   ├── preview.py       # 安全预览（保护路径检查）
│   └── execute.py       # 删除执行（并行 + 批量回收站 + 验证）
│
├── importers/
│   └── winapp2.py       # Winapp2.ini 解析器 + 路径分类
│
└── utils/
    ├── scanner_base.py  # ScanResult / BaseScanner / safe_walk
    ├── size.py           # format_size
    ├── dirtree.py        # dir_total（递归 + LRU 缓存）
    ├── staleness.py      # get_age_days / cache_type_installed
    ├── confidence.py     # 置信度评分引擎
    └── impact.py         # 影响预测 + 生态分组（120+ 映射）
```

## 关键设计决策

### 为什么有 Reflex 层？

传统工具需要 AI "主动思考清理"。Reflex 让清理变成无意识的：
- `check_disk_pulse` = 看都不用看，潜意识自动检查
- `auto_clear_safe` = 只删 "100% 确定" 的，不做决策
- 从 Conscious → Unconscious

### 为什么 reclaim 不做增量？

第一次 reclaim 总是全量扫描（~30s）。因为：
- 缓存后的 `check_disk_pulse` <1ms 已经覆盖了高频检查
- 全量扫描保证数据一致性（磁盘变化不可预测）
- 分阶段执行允许只做需要的阶段

### 为什么 SQLite ？

历史、反馈、信任、Winapp2 数据都用 SQLite。理由:
- 原子写入（避免并发损坏）
- 复杂查询（按 provider 分组统计）
- 迁移能力（加列/加表）
- 多进程访问安全
