# Clyan — 给 AI Agent 用的磁盘清理工具

一个由 AI agent 驱动的命令行磁盘清理工具。你可以通过 CLI 或 MCP 协议与它交互，说一句话就能完成全盘扫描、垃圾识别、空间释放。

## 功能

- **26+ 缓存检测器**：npm / pip / cargo / Go / Docker / IDE 缓存 / 浏览器缓存 / Windows 系统缓存 / 开发垃圾
- **重复文件检测**：三步检测（按大小分组 → BLAKE2b 部分哈希 → 全量哈希）
- **Windows 深度清理**：WinSxS 组件存储、Windows.old 旧系统、DriverStore 驱动备份、Delivery Optimization 缓存、DISM 清理
- **三级安全体系**：Safe（安全可删）/ Caution（谨慎，可能需重建）/ Unsafe（不可删，含配置/凭据），配合保护路径系统和豁免规则
- **垃圾置信度评分**：每个可清理项自动计算 0–100% 置信度（安全级别 + 修改时间 + 工具是否卸载 + 目录名），附中文原因说明
- **孤儿缓存检测**：自动检测包管理器（npm/pip/cargo/go/gradle/dotnet…）是否已卸载，被弃用的缓存自动提高置信度
- **智能过滤**：`--auto-safe`（只删置信度≥90%的项目）、`--min-confidence <0-100>`、`--explain`（显示置信度原因）
- **回收站 + 历史回溯**：默认走回收站，SQLite 记录每次操作，支持按 ID 撤销
- **MCP 服务器**：AI agent 可通过 Model Context Protocol 直接调用所有工具（无需 CLI subprocess）
- **多级并行加速**：Provider 级 + Scanner 级双级并行，配合 LRU 目录尺寸缓存
- **并行清理加速**：Parallel `shutil.rmtree` 批量回收站 + 原生 Windows 删除、`is_protected` LRU 缓存、大小优先排序
- **Windows 原生删除**：≥500MB 大目录自动用 `rd /s /q`（深树提速 1.3x）；散落小目录用并行 `shutil.rmtree`（提速 3.5x）
- **全局包管理器保护**：`%APPDATA%\npm` 等目录受保护，不被误清理

## 性能

| 扫描范围 | 规模 | v0.1.0 | **v0.4.0** | 提速 |
|---------|------|--------|-----------|------|
| 用户目录 `C:\Users\xxx` | ~40 GB | ~23s | **~2.4s** | **~90%** |
| 全盘 `C:\` | ~335 GB | ~未测量 | **~39s** | — |
| 清理 200 散落目录（2K 文件） | 并行 rmtree | ~0.23s | **~0.06s** | **3.5x** |
| 清理 10K 深树文件 | 原生 rd /s /q | ~1.6s | **~1.3s** | **1.3x** |

优化核心：Provider 并行化、大小缓存、WinSxS 免遍历、单次文件系统遍历、线程安全 LRU 缓存。

## 快速开始

```bash
pip install -e .
# 全盘快速体检（2-4 秒完成用户目录，40 秒完成全盘）
clyan scan quick C:\
# 只看大件开发垃圾
clyan scan dev-garbage C:\ --min-size-mb 100
# 预览清理结果（带置信度说明）
clyan clean --items items.json --dry-run --explain
# 只删"绝对垃圾"（置信度≥90% 且安全级别 SAFE）
clyan clean --items items.json --auto-safe
# 执行清理（大文件直接删，不走回收站）
clyan clean --items items.json --fast
```

## 命令

### 扫描

| 命令 | 说明 |
|------|------|
| `scan space <path>` | 目录空间分析 |
| `scan dev-garbage <path>` | 开发者缓存/垃圾 |
| `scan browsers` | 浏览器缓存 |
| `scan system` | Windows 临时文件 + 回收站 |
| `scan duplicates <path>` | 重复文件检测 |
| `scan packages` | 安装的环境包管理器 |
| `scan quick <path>` | 一键全量扫描（并行执行全部分类） |

### 清理

| 选项 | 说明 |
|------|------|
| `--items <file>` | JSON 文件或字符串 |
| `--stdin` | 从 stdin 读取 JSON |
| `--dry-run` | 预览模式（不实际删除） |
| `--permanent` | 永久删除（不进回收站） |
| `--fast` | 大文件直接删（默认 ≥100MB 进回收站） |
| `--safety {safe,caution,unsafe}` | 最小安全级别过滤 |
| `--explain` | 显示置信度分数和原因 |
| `--min-confidence <0-100>` | 只处理置信度≥阈值的项目 |
| `--auto-safe` | 只删置信度≥90% 且 safety=safe 的项目 |

### 其他

| 命令 | 说明 |
|------|------|
| `history` | 查看清理历史 |
| `undo <id>` | 撤销某次清理 |
| `mcp` | 启动 MCP 服务器 |

## 置信度评分

v0.4.0 引入的垃圾置信度引擎自动为每个可清理项打分，帮助你决定哪些可以放心删除。

### 评分公式

| 信号 | 权重 | 最高分 | 说明 |
|------|------|--------|------|
| 安全级别 | 40% | 40 | SAFE=40, CAUTION=20, UNSAFE=0 |
| 文件陈旧度 | 30% | 30 | >90天=30, >30天=20, >7天=10, 近期=0 |
| 工具已卸载 | 20% | 20 | 对应包管理器不在 PATH 中=20 |
| 已知缓存目录名 | 10% | 10 | npm-cache / \_\_pycache\_\_ / Temp / ...=10 |

### 使用场景

```bash
# 看置信度分布 + 每项原因
clyan clean --items items.json --dry-run --explain

# 只删 100% 确定垃圾
clyan clean --items items.json --auto-safe

# 自定义阈值：只删置信度≥80%
clyan clean --items items.json --min-confidence 80 --fast

# 扫描开发垃圾时看置信度
clyan scan dev-garbage C:\Users\tr --explain
```

### 输出示例

```json
{
  "reason": "安全级别 SAFE；>90天未修改；对应工具已卸载；已知安全缓存目录名",
  "confidence": 1.0,
  "age_days": 120,
  "tool_installed": false
}
```

- **置信度 0.8–1.0**：🟢 放心删 — 安全 + 陈旧 + 孤立
- **置信度 0.5–0.8**：🟡 很可能可删 — 安全但工具还在或近期用过
- **置信度 < 0.5**：🔴 谨慎 — CAUTION/UNSAFE 或刚生成

## MCP 服务器

启动 MCP 服务器后，AI agent 可以通过 stdio 传输协议直接调用所有功能：

```bash
clyan mcp
```

暴露的 MCP 工具：
- `scan_quick` / `scan_dev_garbage` / `scan_browsers` / `scan_system` / `scan_duplicates` / `scan_packages`
- `clean_preview` / `clean_execute`
- `history` / `undo`

## 安全体系

采用 **三层危险等级** + **保护路径 + 豁免规则** 的组合策略：

| 等级 | 含义 | 示例 |
|------|------|------|
| 🟢 safe | 可安全删除，自动重建 | `node_modules/`, `.cache/`, `Temp/`, NGEN 镜像 |
| 🟡 caution | 注意 — 可能需重装或重建 | `.venv/`, VS Code 扩展, `.dart_tool` |
| 🔴 unsafe | 不可删 — 含配置/凭据/数据 | `.ssh/`, `.git/`, `Desktop/`, `全局 npm` |

保护路径（31条）：`C:\Windows`、`C:\Program Files`、`%APPDATA%\npm`、`Desktop`、`Documents`、`.ssh`、`.git`……

豁免规则（34条）：`node_modules/`（排除全局 npm）、`Temp/`、`.cache/`、`assembly/`、`dist/`（排除 npm 内）……

## 安装

```bash
pip install -e .
# 或使用 MCP 模式（启动 AI agent 工具服务器）
clyan mcp
```

## 版本历程

| 版本 | 亮点 |
|------|------|
| **v0.4.0** | 垃圾置信度评分引擎 + 孤儿缓存检测 + --explain/--min-confidence/--auto-safe |
| **v0.3.0** | 清理性能优化：原生 rd/s/q（1.3x）、并行 rmtree（3.5x）、批量回收站、is_protected LRU 缓存 |
| **v0.2.0** | 扫描性能大提速（~90%）：Provider 并行化、目录尺寸缓存、WinSxS 免遍历、单次文件系统遍历 |
| **v0.1.0** | 初始版本：26+ 缓存检测器、重复文件检测、Windows 深度清理、MCP 服务器 |

## 参考项目

Clyan 的设计和实现参考了以下开源项目：

| 项目 | 参考内容 |
|------|---------|
| [TurboClean](https://github.com/ChenAI-TGF/TurboClean) | 多进程磁盘扫描框架 |
| [Czkawka](https://github.com/qarmin/czkawka) | 重复文件检测策略、临时文件扫描 |
| [ddh](https://github.com/darakian/ddh) | 轻量重复文件查找 + JSON 输出格式 |
| [bleachbit](https://github.com/bleachbit/bleachbit) | 安全边界模型、保护路径 XML、系统清理 |
| [cache-commander](https://github.com/juliensimon/cache-commander) | Provider 模块化架构、MCP 集成、SafetyLevel 设计 |
| [null-e](https://github.com/us/null-e) | 50+ 缓存类型覆盖、Windows 支持 |
| [dev-cleaner](https://github.com/jemishavasoya/dev-cleaner) | Windows 全栈开发者缓存路径 |
| [dustoff](https://github.com/westpoint-io/dustoff) | JS/TS 构建产物清理 |
| [modclean](https://github.com/ModClean/modclean) | node_modules 深度瘦身 |
| [space](https://github.com/emilevr/space) | Rust 磁盘分析器 TUI/CLI 设计 |
| [cull](https://github.com/legostin/cull) | 交互式 TUI 磁盘分析 |
