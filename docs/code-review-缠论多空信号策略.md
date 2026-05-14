# Code Review: `examples/B_缠论多空信号策略.py`

**Reviewer:** Claude (engineering:code-review)
**Date:** 2026-05-07
**Lines reviewed:** 1515
**Context:** 用户即将基于此文件复制改造 5m 周期版本（见 ADR-001）。先把原文件的问题修掉，避免缺陷复制到 5m 版本。

---

## Summary

整体策略逻辑设计完整 — 四类信号检测、信号优先级聚合、ATR / 结构 / 中枢三重止损都到位，可视化输出齐全。但**有两个 P0 阻塞性 bug 让这份脚本目前根本无法独立运行**，另外有几处中等风险的正确性和性能问题应在拷贝到 5m 版本之前一并修掉。

---

## Critical Issues（必须修，阻塞运行）

| # | File | Line | Issue | Severity |
|---|------|------|-------|----------|
| 1 | `B_缠论多空信号策略.py` | 1044, 1051, 1059, 1091, 1306, 1309, 1342–1346 | **`os` 模块从未导入。** 全文搜索 `^import os` 无结果，但 `save_signals_to_file` 和 `plot_chanlun_chart` 多处调用 `os.makedirs` / `os.path.join` / `os.path.abspath`。一旦回测结束触发可视化或信号导出，立即 `NameError: name 'os' is not defined`。 | Critical |
| 2 | `B_缠论多空信号策略.py` | 1313–1514 | **整个"主程序"块是死代码。** `plot_chanlun_chart` 在 1310 行 `return chart_path` 结束后没有 dedent 也没有 `if __name__ == "__main__":` — 1314 行往后的 200 行 `RUN_MODE` / `config` / `runner.run(...)` 全部在 4 空格缩进上，Python 把它们当成 `plot_chanlun_chart` 函数体内 `return` 之后的不可达代码。**脚本直接 `python B_缠论多空信号策略.py` 不会执行任何交易逻辑，只是定义函数。** | Critical |
| 3 | 同上 | 1233 (`signals_history` 引用) → 实际触发于 1488 调用处 | 因为 #2 是死代码，整个回测后处理（图表 + CSV 导出）根本不会被调用。用户以为生成的 `chanlun_*.png` 永远不会出现。 | Critical |

### 修复建议

```python
# 文件顶部新增
import os

# 把 1313 行起的所有内容 dedent 到 0 缩进，并包在主入口里
if __name__ == "__main__":
    # ========== 运行模式 ==========
    RUN_MODE = RunMode.BACKTEST
    # ... 其余配置代码 dedent 4 空格
```

---

## High Severity Issues（强烈建议修）

| # | File | Line | Issue | Severity |
|---|------|------|-------|----------|
| 4 | `B_缠论多空信号策略.py` | 358–402 | **`detect_type1_signal` 把端点拆成 `highs` / `lows` 后按下标取值，假设端点严格交替。** 如果上游 `extract_bi_endpoints` 由于笔合并产生连续两个同向端点（czsc 边界条件下偶发），下标 `lows[0]` 实际可能不是时间最早的那个低点，会得到错乱的"低点抬高"判定。建议改为按 `dt` 排序后按时间顺序两两配对。 | High |
| 5 | `B_缠论多空信号策略.py` | 252–267 | **`extract_bi_endpoints` 第一个端点的 `bi_index = 0` 与后续端点语义不一致。** 后续端点的 `bi_index` 表示"对应笔的索引"，但首端点是首笔的**起点**，把它也标 `bi_index=0` 容易导致下游误把 endpoint[0] 和 endpoint[1] 关联到同一笔。给首端点单独标 `bi_index=-1` 或在结构里区分 start/end 更安全。 | High |
| 6 | `B_缠论多空信号策略.py` | 770–789 | **每根 K 线都把整个 DataFrame 重新转为 RawBar 列表，再做一次 `len` 比较取增量。** `kline_to_rawbar` 对 N 根 K 线遍历 N 次（O(N) 拷贝），即使后续只 update 新的几根。回测 5 万根 K 线时这是 O(N²) 行为。改为只把"自上次以来新增的那几根"转成 RawBar 即可，把已转换过的旧 bars 缓存起来。 | High |
| 7 | `B_缠论多空信号策略.py` | 859–878 | **信号触发时 `g_chanlun_state.entry_price = current_price`，但 `current_price` 是当前 bar 的价格，而下单 `order_type='next_bar_open'` 实际成交在下一根 bar 开盘价。** 之后 ATR 止损用 `entry_price - atr_stop_multiplier * atr` 比对，会基于错误的入场价，止损位置系统性偏差。建议从 `api` 拿到实际成交价再写 entry_price，或下单时记录意图价、成交后回填。 | High |

---

## Medium Severity Issues

| # | File | Line | Issue | Severity / Category |
|---|------|------|-------|---------------------|
| 8 | `B_缠论多空信号策略.py` | 919, 905 | `api.sell()` 和 `api.buycover()` 调用没有传 `volume` 参数，依赖框架默认"全平"。如果框架后续语义变了（比如默认平 1 手），所有平仓都变成部分平仓 — 严重风险但是隐式依赖。建议显式传 `volume=abs(current_pos)`。 | Medium / Correctness |
| 9 | `B_缠论多空信号策略.py` | 141–148 | **大量模块级全局变量** `g_chanlun_state` / `g_signals_history` / `g_klines_snapshot` / `g_zs_history`。在 BACKTEST 单线程下 OK，但在 SIMNOW / REAL_TRADING 模式下若有 TICK 回调并发或多品种共用同一策略文件，会数据串台。`initialize` 里有重置但没加锁。封装到一个 dataclass 实例并通过 `api` 注入更安全。 | Medium / Correctness |
| 10 | `B_缠论多空信号策略.py` | 793–802 | **当 `len(bi_list) == g_chanlun_state.last_bi_count` 时直接 return**，但仍需检查止损 — 这一行是对的。但有个边界：如果 `bi_list` 长度不变但内容变了（czsc 内部把最后一笔合并/重画了），策略会错过新形态。可以加个 hash 检查最后一笔的 `fx_b.dt`。 | Medium / Correctness |
| 11 | `B_缠论多空信号策略.py` | 176 | `freq_map.get(freq, Freq.F15)` — 用户传 `'5min'`、`'5'`、`'5M'` 都会**静默回退到 F15**，跨周期数据会被当成 15 分钟笔判定。应该 raise，或至少 `api.log` 警告。 | Medium / Correctness |
| 12 | `B_缠论多空信号策略.py` | 695–708 | `min_bi_len` 参数定义并打印了，但下游没人读它 — 真正影响 czsc 笔判定的是 `CZSC(raw_bars, max_bi_num=100)` 里的 `max_bi_num`。这个参数实际是 dead config，会误导调参的人。要么接进去要么删掉。 | Medium / Maintainability |
| 13 | `B_缠论多空信号策略.py` | 1112, 1309, 1481, 1485 | **多处把"缠论"写成"缩论"**（缩进的"缩"）— 图表标题、控制台输出、注释都中了。生成的图片标题`{symbol} {period} 缩论分析图` 给同事看会很尴尬。 | Medium / Maintainability |
| 14 | `B_缠论多空信号策略.py` | 1121, 1274 注释 | "红涨绻跌" — `绻` 应为 `绿`（输入法问题）。不影响功能但不专业。 | Low / Maintainability |
| 15 | `B_缠论多空信号策略.py` | 264 | 注释说"端点交替形成高点和低点"，但**没有断言验证 czsc 返回的笔严格交替**。如果 czsc 因任何原因返回 direction 重复的相邻笔（比如 update 中间状态），下游 `detect_type1` 等会得到错乱结果。加 `assert` 会快速暴露问题。 | Medium / Correctness |

---

## Low Severity Issues

| # | File | Line | Issue | Category |
|---|------|------|-------|----------|
| 16 | `B_缠论多空信号策略.py` | 622–665 | `aggregate_signals` 优先级映射用"1=最高"反直觉，且 type4 的 V 反与 type1 的转向语义重叠时优先级 4 比 type1 的 3 低 — V 反信号比 1 类信号弱是合理的，但代码没注释说明这个产品决策。 | Style |
| 17 | `B_缠论多空信号策略.py` | 517, 537 | `point_2 >= point_0 * 0.998` — 容忍 0.2% 的"前低破位"判定。这个魔法数字应该提成参数 `low_break_tolerance=0.002`，否则在不同品种（黄金 vs 螺纹）上都用 0.2% 是不合适的。 | Maintainability |
| 18 | `B_缠论多空信号策略.py` | 38–46 | matplotlib 字体配置只在导入时执行一次 — 跨平台 fallback 列表 OK，但 Linux 上 `WenQuanYi Zen Hei` 没装时会回退到 `DejaVu Sans`，中文标签变方块。生产环境最好显式打包字体或在初始化时检查。 | Maintainability |

---

## What Looks Good

- **信号优先级聚合**（622–665）逻辑清晰，多空冲突直接放弃交易，避免左右互搏
- **三重止损**（ATR + 结构 + 中枢）层次合理 — 任一触发即清仓，止损成本可控
- **可视化模块**（1068–1310）完整：蜡烛、笔、线段、中枢矩形（带 ZG/ZD/ZZ 三条线）、买卖点带方向箭头标注。即便修掉 bug 也是基础值得保留的部分
- **数据结构**（`ChanlunSignal`、`BiEndpoint`、`ZS` dataclass）清晰自包含
- **中文字体跨平台 fallback**思路对（38–46），思路 OK 即便实现可以加强
- **信号冷却期**（`signal_cooldown`）防过度交易的设计是对的，5m 版本应该把它放大

---

## Verdict

**🔴 Request Changes** — Issues #1 #2 #3 是阻塞性的，修复前文件无法独立运行。修复 #1 #2 #3 后，4–7 应在拷贝到 5m 版本之前一并修，否则 5m 版本继承同样问题。8–15 可以在第二轮迭代修。

---

## 拷贝到 5m 版本前的最小修复清单

```
[ ] 文件顶部加 import os
[ ] 1314–1514 行 dedent 到 0 缩进，包在 if __name__ == "__main__": 下
[ ] detect_type1_signal 改为按时间排序后两两配对，不再按 highs[i]/lows[i] 取值
[ ] kline_to_rawbar 增量化 — 缓存已转换过的 RawBar 列表
[ ] entry_price 写入改为下单确认后回填，或直接用 next_bar_open 的开盘价
[ ] api.sell() / api.buycover() 显式传 volume=abs(current_pos)
[ ] 全文 "缩论" → "缠论"，"绻" → "绿"
[ ] freq_map 传入未知值时改为 raise，不静默回退
[ ] min_bi_len 参数：要么连到 czsc 调用，要么删掉
```

按 ADR-001 的 P0 行动项 1（"复制改造而非直接改原文件"）执行时，把这份清单的修复同步应用到新文件上即可。
