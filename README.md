# Clyan — 给 AI Agent 的磁盘本体感觉

> **自用非商用开源项目** · AGPL · 一个 AI 知道它"有多满"的磁盘工具

Clyan 不是"磁盘清理工具"。它是 AI Agent 的**磁盘反射弧**——像膝跳反射一样，在 AI 下载大文件之前自动腾出空间，在磁盘将满时自动预警，整个过程**不需要 AI 思考"清理"这件事**。

```bash
# 第一次：用手摸
clyan reclaim C:\           # 全量扫描 → 分阶段执行计划
clyan reclaim C:\ --phase 1 # 执行零风险阶段

# 第二次：条件反射
clyan pulse                  # <1ms 健康检查（缓存预热后零 IO）
clyan auto-clear             # 自动释放 cost=none 项（AI 无感）
```

## 一句话哲学

**工具做"全"和"准"，AI 做"判断"和"决策"。**

Clyan 不做三件事：
- ❌ 不替 AI 判断该删什么（删了 `is_protected` 硬拦截）
- ❌ 不按阈值决定删除方法（删了 `_FAST_THRESHOLD`）
- ❌ 不给 AI "加工"过的数据（全量原始信号返回）

## 功能矩阵

### 🔍 扫描（53+ 内置 Provider + 3700+ Winapp2）

| 层 | 覆盖范围 | provider 数 |
|----|---------|------------|
| 包管理器缓存 | npm / pip / cargo / go / gradle / maven / nuget / pnpm / bun / uv | 12 |
| 构建产物 | node_modules / .next / .angular / .vite / .nx / target / build | 20+ 模式 |
| 游戏/GPU | DirectX / NVIDIA / AMD / Intel 着色器缓存 + Steam / Epic 启动器 | 6 |
| 系统深度 | Windows 事件日志 / 系统还原点 / 空目录 / 零碎小文件 | 5 |
| IDE 缓存 | VS Code / JetBrains / Eclipse / IDEA 扩展+缓存 | 5 |
| 浏览器 | Chrome / Edge / Firefox 完整缓存 + SQLite 深度清理 | 4 |
| Windows 系统 | WinSxS / DISM / DriverStore / Installer / Update / Temp / WER / 缩略图 / 搜索索引 | 15 |
| Windows 扩展 | Delivery Optimization / SoftwareDistribution / Store / Teams / OneDrive / Defender / Xbox / 旧备份 | 8 |
| 应用缓存 | Discord / Slack / Teams / Zoom / WeChat / Spotify / WhatsApp / Obsidian / Flutter / Android | 12 |
| ML/AI | HuggingFace Hub / Ollama / PyTorch / TensorFlow / LM Studio | 5 |
| Winapp2 | 社区维护 3700+ 条清理器定义（自动按路径分类） | 动态 |
| **总计** | | **55+ 固定 + 动态** |

### ⚡ Reflex（磁盘反射弧）

| 级别 | 工具 | 延迟 | AI 意识 | 行为 |
|------|------|------|---------|------|
| **tick** | `check_disk_pulse` | **<1ms** | 写文件前自动调用 | 无感 |
| **twitch** | `auto_clear_safe` | **~1s（缓存命中）** | 无感自动执行 | 只清 cost=none |
| **spasm** | `reclaim --phase` | **~30s（全量）** | 被告知，不做决策 | 分阶段执行 |

### 🧠 行为学习

Clyan 根据 AI 的历史决策动态调整置信度：

```
AI 连续跳过 npm_cache 3 次 → 置信度 -0.10（AI 认为不需要）
AI 连续清理 pip_cache 3 次 → 置信度 +0.05（AI 认为安全）
历史准确率 < 70%            → 置信度 -0.05（校准）
从未见过的新类型            → 置信度 -0.03（保守）
```

### 📋 Reclaim（统一回收计划）

一次扫描，按风险分阶段输出：

```
📋  Reclaim Plan for C:\Users\tr
   Total: 89.21 GB (364 items)
   🟢  Phase none:    28.97 GB (39 items)  — Temp/npx/缩略图
   🟡  Phase low:      1.12 GB (13 items)  — 浏览器缓存
   🟠  Phase medium:   4.52 GB (126 items) — IDE/构建产物
   🔴  Phase high:    25.95 GB (35 items)  — npm/pip/依赖缓存
   ⚫  Phase unknown: 28.65 GB (151 items) — Winapp2 未分类
```

## 性能

| 操作 | 首次 | 缓存后 |
|------|------|--------|
| `pulse`（健康检查） | **178ms**（自动预热） | **<1ms** |
| `scan disk`（全盘概览） | **~7s** | — |
| `scan dev-garbage`（开发者垃圾） | **~8s** | — |
| `reclaim`（全量回收计划） | **~30s** | **~8s**（缓存） |
| `auto-clear`（安全自动清理） | **~15s**（全量扫描） | **~1s**（缓存命中） |
| `duplicates`（重复文件检测） | **~2s**（4KB hash + 并行） | — |

## 快速开始

```bash
pip install -e .

# 磁盘反射弧——AI 的无意识层
clyan pulse                          # <1ms 健康检查
clyan auto-clear                     # 自动释放安全空间

# 统一回收计划
clyan reclaim C:\                    # 全量扫描 → 分阶段计划
clyan reclaim C:\ --phase none       # 只执行零风险阶段

# 传统扫描
clyan scan disk C:\ --depth 2       # 磁盘概览
clyan scan dev-garbage C:\ --explain # 开发者垃圾 + 置信度
clyan scan quick C:\                 # 全量快速体检
clyan scan files C:\ --min-size 100  # 大文件发现

# 一键深清
clyan clean --deep --strategy safe --yes

# MCP 服务器（给 AI Agent 用）
clyan mcp
```

## 命令参考

### 扫描

| 命令 | 说明 |
|------|------|
| `scan space <path>` | 目录空间分析（--depth, --top） |
| `scan dev-garbage <path>` | 开发者缓存/垃圾 + Winapp2 + 置信度 |
| `scan browsers` | 浏览器缓存（Chrome/Edge/Firefox） |
| `scan system` | Windows 临时文件 + Temp 深度分解 |
| `scan duplicates <path>` | 重复文件（4KB hash + 并行 + inode 去重） |
| `scan packages` | 包管理器环境检测 |
| `scan disk [drive]` | 磁盘概览：容量/已用/剩余/目录树/可回收 |
| `scan files <path>` | 大文件发现（--min-size, --top） |
| `scan node-waste <path>` | node_modules 内部瘦身 |
| `scan quick <path>` | 一键全量扫描 |

### 反射

| 命令 | 说明 |
|------|------|
| `pulse [path]` | **⚡ 磁盘健康检查**（<1ms，缓存的） |
| `auto-clear [path]` | **⚡ 自动释放 cost=none 空间** |

### 回收

| 命令 | 说明 |
|------|------|
| `reclaim <path>` | **全量扫描 → 分阶段执行计划** |
| `reclaim <path> --phase none` | 执行零风险阶段 |
| `reclaim <path> --dry-run` | 预览不执行 |

### 清理

| 选项 | 说明 |
|------|------|
| `--dry-run` | 预览（不删除） |
| `--deep --strategy safe` | 一键深清：扫描→评分→过滤→执行→验证 |
| `--dedupe keep-newest` | 去重（保留最新） |
| `--auto-safe` | 只删置信度≥90% 且 safety=safe |
| `--explain` | 显示置信度原因 + 影响预警 |

### 其他

| 命令 | 说明 |
|------|------|
| `history` | 清理历史 |
| `undo <id>` | 撤销清理 |
| `trust add/remove/list` | 受信任路径（跳过保护警告） |
| `import winapp2 <file>` | 导入 Winapp2.ini |
| `mcp` | 启动 MCP 服务器（23 工具） |
| `schedule --create` | 每周定时清理 |

## MCP 服务器（23 工具）

```bash
clyan mcp
```

| 工具 | 功能 |
|------|------|
| `check_disk_pulse` | ⚡ **反射 tick**：<1ms 健康检查 |
| `auto_clear_safe` | ⚡ **反射 twitch**：零决策安全清理 |
| `reclaim` | 📋 **统一回收**：全量→分阶段→执行 |
| `scan_quick` | 全量扫描（55 provider） |
| `scan_dev_garbage` | 开发者垃圾 + Winapp2 |
| `scan_browsers` | 浏览器缓存 |
| `scan_system` | Windows 系统临时文件 |
| `scan_duplicates` | 重复文件检测 |
| `scan_packages` | 包管理器检测 |
| `scan_disk` | 磁盘概览 |
| `get_confidence_summary` | 置信度评分 + 影响预警 |
| `clean_propose` | 阶段 1：提议清理 |
| `clean_confirm` | 阶段 2：确认执行 |
| `clean_auto` | 一键自主清理 |
| `clean_deep` | 完整清理周期 |
| `clean_preview` | 预览检查 |
| `clean_execute` | ⚠ 执行删除 |
| `clean_plan` | 按 recovery_cost 排序的清理计划 |
| `system_health` | 系统健康检查 |
| `get_provider_feedback` | provider 历史准确率 |
| `history` | 清理历史 |
| `undo` | 撤销清理 |

## AI 决策信号

每个扫描项返回的完整信号：

```json
{
  "path": "C:\\Users\\tr\\AppData\\Local\\pip\\cache",
  "size": 3380000000,
  "size_human": "3.38 GB",
  "provider": "python",
  "confidence": 0.50,
  "reason": "安全级别 SAFE；>90天未修改；工具仍在；已知缓存目录；重建成本高",
  "would_break": ["pip install would re-download all packages from PyPI"],
  "would_affect": ["pip", "python", "virtualenv"],
  "recovery_cost": "high",
  "ecosystem": "python",
  "age_days": 120,
  "tool_installed": true
}
```

| 字段 | 用途 | 示例 |
|------|------|------|
| `confidence` | 置信度 0.0–1.0 | 0.50 |
| `reason` | 中文评分原因 | "安全级别 SAFE；>90天未修改…" |
| `would_break` | 删除后果 | ["pip install would re-download…"] |
| `would_affect` | 影响的应用 | ["pip", "python", "virtualenv"] |
| `recovery_cost` | 恢复成本 | "high" / "medium" / "low" / "none" |
| `ecosystem` | 生态分组 | "python" / "node" / "windows" |
| `age_days` | 未使用天数 | 120 |
| `tool_installed` | 工具是否仍在 | true |

## 版本历程

| 版本 | 亮点 |
|------|------|
| **v1.0.0-rc** | Reflex 反射弧 + reclaim 统一回收 + 行为学习 + GPU 缓存 + 多驱动器 + 55 provider |
| **v0.19.0** | Windows Installer 缓存 / DISM 集成 / npm 裁剪 / Winapp2 路径分类 |
| **v0.18.0** | npm/pip 缓存深度分解（_npx / _cacache / 年龄分组） |
| **v0.17.0** | Winapp2 导入引擎（3700+ 社区清理器） |
| **v0.16.0** | 历史准确率 + clean_plan MCP 工具 |
| **v0.15.0** | 信任系统 + system_health MCP |
| **v0.14.0** | Agent 反馈闭环 + clyan trust |
| **v0.13.0** | 影响预测（would_break / recovery_cost）+ 生态分组 |
| **v0.10.0** | 执行层精简：AI 全权决策 |
| **v0.7.0** | 置信度引擎（6 信号 + 重建成本） |
| **v0.4.0** | 垃圾置信度评分 |
| **v0.2.0** | Provider 并行化（~90% 提速） |
| **v0.1.0** | 初始版本：26+ 检测器 + MCP |

## 参考项目

| 项目 | 参考内容 |
|------|---------|
| [Winapp2](https://github.com/MoscaDotTo/Winapp2) | 3700+ 社区清理器定义 |
| [Czkawka](https://github.com/qarmin/czkawka) | 重复文件检测策略 |
| [ddh](https://github.com/darakian/ddh) | 轻量重复文件查找 |
| [bleachbit](https://github.com/bleachbit/bleachbit) | 安全边界模型 |
| [cache-commander](https://github.com/juliensimon/cache-commander) | Provider 模块化架构 + MCP 集成 |
| [dustoff](https://github.com/westpoint-io/dustoff) | JS/TS 构建产物清理 |
| [modclean](https://github.com/ModClean/modclean) | node_modules 深度瘦身 |

## 许可证

自用非商用开源项目（AGPL）。仅供个人学习、研究使用。禁止商业用途。

**免责声明：** 本工具会删除文件。虽然设计了多层安全保护，但不能保证 100% 避免误删。使用前请备份重要数据。作者不对因使用本工具造成的任何直接或间接损失承担责任。
