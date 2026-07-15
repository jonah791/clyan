# Clyan 架构文档

> 版本 0.17.0 · 自用非商用开源项目

## 设计理念

Clyan 的核心原则：**工具做"全"和"准"，AI 做"判断"和"决策"**。

```
扫描层 → 全面发现 + 全量信号（不过滤、不设阈值）
执行层 → 安全执行 + 报告副作用（不硬拦截、不替 AI 选策略）
AI     → 分析信号 + 做判断 + 选删除方法（trash/direct/native）
```

### 与其他工具的本质区别

| 方面 | 传统工具 (BleachBit/Czkawka) | Clyan |
|------|------------------------------|-------|
| 目标用户 | 人类 | AI Agent |
| 交互方式 | GUI/TUI | MCP 协议 + CLI |
| 决策者 | 用户手动选 | AI 分析信号后决策 |
| 安全模型 | 硬编码保护路径 | 保护路径 + AI 可信任豁免 |
| 学习能力 | 无 | 持久化历史 + 准确率追踪 |

## 系统架构

```
┌──────────────────────────────────────────────────┐
│                    CLI (cli.py)                   │
│   scan / clean / history / trust / import / mcp   │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│                 MCP Server (19 tools)              │
│  scan_* / clean_* / history / system_health / ... │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│                   Scan Pipeline                    │
├──────────────────┬───────────────────────────────┤
│  fast_scan       │  providers.detect_all()        │
│  (目录模式匹配)   │  (45 个注册 provider)          │
│  50+ 构建目录    │  ┌─────────────────────────┐   │
│  match-and-stop  │  │ 内置 36 个              │   │
│                  │  │ Winapp2 动态加载 3377 个  │   │
│                  │  └─────────────────────────┘   │
├──────────────────┴───────────────────────────────┤
│              ScanResult.to_dict()                  │
│  → _enrich 附加: age_days / tool_installed        │
│  → attach_impact: would_break / ecosystem         │
│  → compute_and_attach: confidence / reason        │
│  → _get_provider_accuracy: historical_accuracy    │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────▼─────────────────────────────┐
│                Execution Pipeline                  │
├──────────────────────────────────────────────────┤
│  delete_items(items, use_trash, fast)             │
│  → 逐项 method: trash / direct / native / auto    │
│  → before/after free space 测量                   │
│  → 返回 actual_freed / delta / protected_warned   │
│  → record_clean 写入历史 + clean_feedback         │
└──────────────────────────────────────────────────┘
```

## 数据流

### 扫描流程

1. CLI/MCP 收到扫描请求
2. 并行执行:
   - `fast_scan()` — 目录模式匹配（node_modules, .next, .cache 等）
   - `providers.detect_all()` — 45 个注册 provider 并发运行
3. 结果汇聚到 `ScanResult`
4. `to_dict()` 时逐项:
   - `_enrich()` → `age_days`, `tool_installed`
   - `attach_impact()` → `would_break`, `would_affect`, `recovery_cost`, `ecosystem`
   - `compute_and_attach()` → `confidence`, `reason`
   - `_get_provider_accuracy()` → `historical_accuracy`
5. 返回结构化 JSON

### 清理流程

1. AI 调用 `clean_propose`（两阶段）或 `clean_execute`（直接）
2. 逐项检查 `method` 字段（trash / direct / native / auto）
3. 并行执行删除
4. 测量清理前后磁盘空间
5. 写入 `clean_history` + `clean_feedback`（按 provider 记录准确率）
6. 返回 `actual_freed`, `delta`, `protected_warned`

## 模块结构

```
clyan/
├── __init__.py          # 版本号
├── __main__.py          # python -m clyan 入口
├── cli.py               # CLI 解析 + 命令分发
├── mcp_server.py        # MCP 服务器（19 工具）
│
├── core/
│   ├── config.py        # 保护路径 / 豁免规则 / DangerLevel
│   └── history.py       # SQLite 历史 + 反馈 + 信任系统 + Winapp2 表
│
├── scan/
│   ├── space.py         # 目录空间分析
│   ├── dev_garbage.py   # 开发者垃圾（fast_scan + providers）
│   ├── system.py        # Windows 临时文件
│   ├── browser_cache.py # 浏览器缓存
│   ├── duplicates.py    # 重复文件（4KB hash + 并行 + inode 去重 + 持久缓存）
│   ├── large_files.py   # 大文件发现
│   ├── fast_scanner.py  # 目录模式匹配引擎
│   ├── disk_summary.py  # 磁盘概览 + 趋势
│   ├── node_waste.py    # node_modules 内部瘦身
│   ├── browser_deep.py  # Chrome/Edge/Firefox SQLite 深度清理
│   ├── packages.py      # 包管理器环境检测
│   └── providers/
│       ├── __init__.py  # CacheItem / register / detect_all
│       ├── node.py / python_prov.py / rust_prov.py / ...
│       ├── win_deep.py  # WinSxS / DriverStore / DISM
│       ├── windows_system.py / windows_extra.py
│       ├── app_caches.py
│       └── winapp2_prov.py  # 动态加载 3377 社区清理器
│
├── clean/
│   ├── preview.py       # 安全预览（保护路径检查）
│   └── execute.py       # 删除执行（并行 + 批量回收站 + 验证）
│
├── importers/
│   └── winapp2.py       # Winapp2.ini 解析器
│
└── utils/
    ├── scanner_base.py  # ScanResult / BaseScanner / safe_walk / _enrich
    ├── size.py           # format_size
    ├── dirtree.py        # dir_total（递归目录大小 + LRU 缓存）
    ├── staleness.py      # get_age_days / cache_type_installed
    ├── confidence.py     # 置信度评分引擎
    └── impact.py         # 影响预测 + 生态分组
```

## 关键设计决策

### 为什么用 SQLite 而不是 JSON 文件？

历史、反馈、信任、Winapp2 数据都用 SQLite。理由:
- 支持原子写入（避免并发损坏）
- 支持复杂查询（按 provider 分组统计）
- 支持迁移（加列/加表）
- 支持多进程访问

### 为什么 provider 用模块级注册而不是配置？

`register("name", func)` 在 import 时自动注册。理由:
- 零配置：加新 provider = 加一个文件 + 一行 import
- 延迟加载：Winapp2 的 3377 条目从 DB 动态加载，不增加启动时间
- 可组合：provider 间无依赖，各自独立

### 为什么扫描结果要逐项 enrich？

`to_dict()` 时调用 `_enrich` / `compute_and_attach` / `attach_impact`。理由:
- 避免扫描时做不必要的工作（某些字段只在输出时需要）
- 统一 enrich 点，确保所有输出路径一致（CLI / MCP）
- 缓存友好：`_get_provider_accuracy` 有内存缓存，避免重复 DB 查询
