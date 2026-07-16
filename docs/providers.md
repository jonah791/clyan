# 缓存检测器开发指南

> Clyan 的 provider 系统是可插拔的架构。每个 provider 是一个独立的扫描函数，通过 `register()` 注册后自动集成到扫描管线中。当前共 **56+ 固定 provider + 动态 Winapp2 (3377 清理器)**。

## 架构概览

```
provider 函数: (root: str) -> list[CacheItem]
                      ↓
            register("name", func)
                      ↓
           detect_all() 并发执行全部
                      ↓
            _attach_signals() + enrich + impact + confidence
                      ↓
            ScanResult.to_dict() → 输出
```

## 三层架构

新 provider 建议使用 `@register_provider` 装饰器，自动处理全部安全层：

```python
@register_provider("my_provider", ecosystem="app", default_cost="low")
def _scan_my(root):
    """Layer 1: 纯发现，不做判断"""
    ...
    yield CacheItem(path=path, size=size, label="MyApp Cache")
# Layer 2 (安全层) 自动: is_protected / SafetyLevel / age_days / impact / confidence
# Layer 3 (汇报层) 自动: build_report() / Phase / recommendation
```

## 快速开始

创建一个 provider 只需三步：

### 1. 创建文件

`clyan/scan/providers/my_provider.py`:

```python
import os
from . import CacheItem, SafetyLevel, register
from ...utils.dirtree import dir_total


def _scan_my_app(root: str) -> list[CacheItem]:
    results = []
    cache_dir = os.path.join(
        os.environ.get("LOCALAPPDATA", ""),
        "MyApp", "Cache"
    )
    if os.path.isdir(cache_dir):
        sz = dir_total(cache_dir)
        if sz > 0:
            results.append(CacheItem(
                path=cache_dir,
                size=sz,
                provider="my_app",
                label="MyApp Cache",
                safety=SafetyLevel.SAFE,
                extra={
                    "type": "my_app_cache",
                    "rebuild_cost": "low",
                    "note": "MyApp application cache",
                },
            ))
    return results


register("my_app", _scan_my_app)
```

### 2. 注册到自动加载

在 `clyan/scan/providers/__init__.py` 的 import 行末尾加上:

```python
from . import node, python_prov, ..., my_provider
```

### 3. 完成

下次 `scan dev-garbage` 或 `detect_all()` 会自动包含你的 provider。

## CacheItem 字段

| 字段 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `path` | ✅ | string | 缓存/文件的完整路径 |
| `size` | ✅ | int | 字节大小 |
| `provider` | ✅ | string | provider 标识符（英文小写） |
| `label` | ✅ | string | 人类可读标签 |
| `safety` | ✅ | SafetyLevel | SAFE / CAUTION / UNSAFE |
| `confidence` | — | float | 预设置信度（会被引擎覆盖） |
| `extra` | — | dict | 附加信号 |

### extra 建议字段

| 字段 | 说明 | 影响 |
|------|------|------|
| `type` | 子类型标识 | 决定影响预测的细分 |
| `rebuild_cost` | none / low / high | 覆盖自动推断 |
| `note` | AI 可读的说明 | 附加到 would_break |

## SafetyLevel 选择

| 等级 | 含义 | 适用场景 |
|------|------|---------|
| `SAFE` | 安全可删，自动重建 | 缓存、临时文件、构建产物 |
| `CAUTION` | 注意，可能需重建 | 虚拟环境、IDE 缓存、大模型缓存 |
| `UNSAFE` | 不可删，含配置/凭据 | 配置文件、密钥、用户数据 |

## 现有 provider 参考（53+）

### 包管理器缓存（12）
| Provider | 扫描逻辑 | 说明 |
|----------|---------|------|
| `npm_cache` | `dir_total(npm-cache)` | npm 全局缓存 |
| `npm_deep` | 拆解 _npx / _cacache / npm_global | **深度分解，按年份/类型分组** |
| `npm_prune` | npm cache ls + 年龄信号 | **主动裁剪，3882 entries** |
| `pip_cache` | `dir_total(pip/cache)` | pip wheel 缓存 |
| `pip_deep` | 按 6 个时间区间统计 wheel | **年龄分组，区分新旧** |
| `cargo_registry` | `dir_total(.cargo/registry)` | Rust 依赖缓存 |
| `go_cache` | `dir_total(go/pkg/mod)` | Go 模块缓存 |
| `pnpm_cache` | `dir_total(pnpm/store)` | pnpm 存储 |

### Windows 系统（15）
| Provider | 扫描逻辑 | 说明 |
|----------|---------|------|
| `win_deep` | DISM 分析 WinSxS/DriverStore | 组件存储 + 驱动 |
| `windows_installer` | 按类型/年龄分析 Installer | **旧补丁/旧安装源/大文件三级** |
| `dism_cleanup` | DISM 命令级建议 | **StartComponentCleanup/ResetBase** |
| `windows_extra` | 8 个子 provider | DO / Store / Teams / OneDrive / Defender / Xbox / 备份 |
| `system_temp` | Temp 递归扫描 | 临时文件 + 孤儿目录 |

### 游戏/GPU 缓存（6）
| Provider | 扫描逻辑 | 说明 |
|----------|---------|------|
| `gpu_caches` | NVIDIA DXCache / GLCache / DirectX / AMD / Intel / Steam | **着色器缓存，游戏运行时自动重建** |
| `gpu_caches:system_restore` | vssadmin 查询 | 系统还原点占用 |

### 深度裁剪 provider
| Provider | 覆盖范围 | 分解方式 |
|----------|---------|---------|
| `npm_deep` | npm 缓存 11.3 GB | _npx (1.4 GB, cost=none), _cacache (6.2 GB), npm_global (3.8 GB) |
| `pip_deep` | pip 缓存 3.6 GB | 按 6 个时间区间 + old_ratio |
| `windows_installer` | Installer 5.6 GB | 旧 MSP 补丁 / 旧 MSI / 大文件 |
| `dism_cleanup` | WinSxS/DriverStore | 4 个 DISM 命令级建议 |

## Provider 最佳实践

### 路径获取

优先使用环境变量而非硬编码路径:

```python
os.environ.get("LOCALAPPDATA", "")
os.environ.get("APPDATA", "")
os.environ.get("USERPROFILE", "")
os.environ.get("WINDIR", "C:\\Windows")
os.environ.get("ProgramData", "C:\\ProgramData")
```

### 大小计算

使用 `dir_total(path)` 递归计算目录大小。它自带 LRU 缓存和多 provider 并发安全:
- 对大目录（>1 GB）会自动优化
- 结果被缓存，同次扫描中重复调用立即返回

### 深度拆分

对于大的缓存目录（如 npm-cache 9 GB），建议按子组件拆分：
- 不同子目录有不同 `recovery_cost`
- AI 可以只删 cost=none 的部分（如 _npx）而保留其他

### Winapp2 风格

如果你的 provider 适用于特定 Windows 应用，考虑改为 Winapp2.ini 条目:

```bash
clyan import winapp2 winapp2.ini
```

Winapp2 社区维护着 3700+ 清理器定义。新增一个只需要在 winapp2.ini 中加几行:

```ini
[MyApp Cache]
LangSecRef=Applications
DetectFile=%ProgramFiles%\MyApp\app.exe
FileKey1=%LOCALAPPDATA%\MyApp\Cache|*.*|RECURSE
```

## 影响预测映射

创建 provider 后会自动套用影响预测。如需自定义，在 `utils/impact.py` 的 `_IMPACT_DB` 中添加:

```python
"my_app": (
    ["MyApp cache cleared -- will be re-downloaded on next sync"],
    ["my_app"],
    "low",
),
```

如需按 type 细分:

```python
"my_app:cache": (["..."], ["..."], "low"),
"my_app:logs": (["..."], ["..."], "none"),
```

## 生态分组

在 `utils/impact.py` 的 `_ECOSYSTEM_MAP` 中指定 provider 的生态组:

```python
"my_app": {"my_app", ...},
```

可选的生态组: `node`, `python`, `rust`, `go`, `java`, `dotnet`, `browser`, `ide`, `windows`, `ml`, `build`, `app`, `other`
