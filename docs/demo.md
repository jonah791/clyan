# Clyan AI Demo — 感知·决策·执行闭环

> 这是一段真实的 AI 与 Clyan 交互演示，展示了 AI agent 如何通过 Clyan 的 MCP 工具自主管理磁盘空间。

---

## 场景：AI 自动检查磁盘健康

每次对话开始，AI 自动调用：

```
→ check_disk_pulse(C:\)
← {
    "status": "healthy",
    "free_gb": 122.9,
    "free_pct": 28.1,
    "safe_reclaimable_gb": 1.4,
    "cached": true,
    "ellapsed_ms": 0.0
  }
```

⏱ **0ms**（缓存命中）。AI 知道磁盘健康，继续对话。

---

## 场景：用户说"C 盘满了"

用户："感觉 C 盘快满了，帮我看看"

AI 不直接回答，而是：
1. **P1 极速** → `check_disk_pulse`（0ms，122.9 GB free — 不紧急）
2. **P2 垃圾检测** → `scan_quick`（2.4s，38.98 GB reclaimable）
3. **评估风险** → 分析 recovery_cost / ecosystem / would_break

```
→ scan_quick(C:\Users\tr)
← {
    "grand_total": "95.95 GB",
    "categories": [
      {"space": "55.74 GB", "device_garbage": "38.98 GB"},
    ]
  }
```

AI 判断：
- 28% 空闲 → 还算健康，但可清理
- npm 缓存 7 GB → 重建成本高，暂不清理
- npx 二进制 1.4 GB → cost=none，**立即清理**

---

## 场景：AI 执行安全清理

```
→ auto_clear_safe(C:\)
← {
    "items_cleared": 3,
    "reclaimed_human": "1.4 GB",
    "protected_paths_skipped": 0
  }
```

AI 清理了 3 项零风险项，释放 1.4 GB。**没有询问用户**——因为这是 reflex 层，不需要判断。

---

## 场景：用户说"node_modules 太多了"

AI：
1. **P3 深度分析** → `scan --phase 3`
2. 发现 `node_modules` 占用 ~9 GB
3. 对每个项目评估 rebuild_cost
4. 只在有 `package-lock.json` 备份的项目上建议清理

---

## 架构闭环

```
用户意图
   ↓
AI 感知 ←── check_disk_pulse (0ms)
   ↓
AI 判断 ←── scan_quick / scan --phase 2 (2-8s)
   ↓
AI 决策 ←── build_report / reclaim (结构化建议)
   ↓
AI 执行 ←── auto_clear_safe / clean_auto (零风险部分)
   ↓
反馈学习 ←── record_clean → adjust_confidence (持续改进)
```

**这是 Clyan 和所有传统磁盘工具的核心差异。**

BleachBit/CCleaner/czkawka 需要人类：打开→扫描→勾选→确认→执行。
Clyan 让 AI：感知→判断→决策→执行→学习。整个过程可以无人参与。
