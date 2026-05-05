# SSQuant — AI Agent 项目上下文

> **Version**: 0.4.5  
> **License**: MIT  
> **Language**: Python 3.9–3.14  

---

## 项目定位

SSQuant（松鼠Quant）是中国期货 CTP 量化交易框架，支持**一套代码三处运行**：回测 / SIMNOW 仿真 / 实盘。

**v0.4.5 核心变化**：
- 回测速度 **30×–100×** 提升（ndarray 缓存 + IndicatorCache v2 + 增量账户状态）
- 新增**本地数据模式**（`data_source_mode='local'`），免会员直读 SQLite
- 许可证从 Proprietary 改为 **MIT**
- PyPI 仅保留 redirect 包，真实安装必须通过 `git+https://github.com/songshuquant/ssquant.git`

---

## 目录结构

```
ssquant/
├── api/
│   └── strategy_api.py          # StrategyAPI（策略唯一入口，含 IndicatorCache / ndarray 接口）
├── backtest/
│   ├── backtest_core.py         # 回测引擎主循环（热点优化核心）
│   ├── unified_runner.py        # 统一运行器（BACKTEST / SIMNOW / REAL_TRADING）
│   ├── live_trading_adapter.py  # 实盘/SIMNOW 桥接（Tick 队列、智能追单、移仓）
│   ├── backtest_results.py      # 权益曲线计算（__slots__ 纯对象优化）
│   ├── rollover_engine.py       # 自动移仓引擎
│   └── rollover_audit.py        # 移仓复盘日志
├── config/
│   ├── trading_config.py        # 默认参数、账户配置（仅数据，逻辑抽离到 config_helpers）
│   ├── config_helpers.py        # get_config()、连续合约解析等业务逻辑
│   └── _server_config.py        # data_server 连接配置
├── data/
│   ├── data_source.py           # DataSource（ndarray 缓存、本地模式、IndicatorCache）
│   ├── api_data_fetcher.py      # REST API + SQLite 缓存
│   ├── local_data_loader.py     # 本地 SQLite 导入/加载
│   ├── local_adjust.py          # 前复权/后复权
│   └── contract_mapper.py       # 888/777/000 连续合约映射
├── ctp/py39~py314/              # CTP 二进制（.pyd/.dll/.so）
├── pyctp/                       # CTP 客户端封装
└── indicators/

examples/                          # 策略示例（含 *_高性能.py 版本）
ai_agent/                          # AI 策略助手（前端 + 后端）
045/SKILL.md                       # 完整框架指南（909 行，面向用户/Agent）
```

---

## 关键约定

1. **策略唯一入口**：`StrategyAPI`（`buy / sell / sellshort / buycover / close_all`）
2. **连续合约**：`888`（主力）、`777`（次主力）、`000`（指数）
3. **复权类型**：`adjust_type='0'` 不复权 / `'1'` 后复权 / `'2'` 前复权
4. **数据模式**：
   - `data_source_mode='data_server'`（默认）：远程 API，需会员账号
   - `data_source_mode='local'`：本地 SQLite，免会员，TICK 回测强制使用
5. **移仓模式**：`simultaneous`（同时平旧开新）/ `sequential`（先平后开）
6. **默认高性能写法**：所有策略必须在 `initialize(api)` 中用 `api.register_indicator()` 注册指标，`strategy()` 中 O(1) 查表。普通 Pandas 写法仅作为 fallback
7. **不再支持 PyPI**：仅通过 Git 仓库安装

---

## 编码规范

- **所有交易操作**必须通过 `StrategyAPI`，禁止直接操作底层 CTP 接口
- **策略函数签名**：`def strategy(api: StrategyAPI):` 或 `def strategy(api: StrategyAPI, params: dict):`
- **initialize 钩子（必需）**：`def initialize(api: StrategyAPI):`，**默认在此注册所有指标**。AI 写策略时，优先使用 `api.register_indicator()` + `api.get_indicator()` / `api.get_indicator_array()`
- **回退条件**：仅当指标逻辑无法用 `register_indicator` 表达（如动态窗口、实时跨品种复杂计算、非滚动型状态机）时，才回退到 Pandas 普通写法
- **日志**：回测用 `api.log()`，实盘用 `api.log()`（框架自动区分）
- **异常处理**：实盘策略应捕获异常，避免单根 K 线报错导致整个进程退出

---

## 常见陷阱

| 问题 | 原因 | 解决 |
|------|------|------|
| `ModuleNotFoundError: No module named 'ssquant'` | 从 PyPI 安装了 redirect 包 | 卸载后通过 Git 安装：`pip install git+https://github.com/songshuquant/ssquant.git` |
| 回测无数据 | 远程模式鉴权失败 或 本地模式无数据 | 检查 `data_source_mode`；本地模式先运行 `examples/A_工具_导入数据库DB示例.py` |
| TICK 回测报错 | TICK 数据不支持远程模式 | 必须设置 `data_source_mode='local'` |
| 策略在 SIMNOW/实盘指标值不对 | 未使用 IndicatorCache v2 | `register_indicator` 在三模式通用，默认必须使用 |
| 回测速度远低于预期 | 策略内使用 Pandas `rolling/ewm/iloc` 重复计算 | 将指标注册到 `initialize()`，策略内仅做 O(1) 查表 |
| 多品种回测数据错位 | `align_data=True` 导致不同周期数据源被错误截断 | 多品种多周期通常设为 `align_data=False` |

---

## 关键文件速查

| 需求 | 文件 |
|------|------|
| 最新更新详情 | `045.MD` |
| 框架完整指南 | `045/SKILL.md` |
| 项目 README | `README.md` |
| AI Agent 上下文 | `AGENTS.md`（本文件） |
| 策略 API | `ssquant/api/strategy_api.py` |
| 回测引擎 | `ssquant/backtest/backtest_core.py` |
| 三模式统一入口 | `ssquant/backtest/unified_runner.py` |
| 数据源/缓存 | `ssquant/data/data_source.py` |
| 配置生成 | `ssquant/config/config_helpers.py` |
| 合约映射 | `ssquant/data/contract_mapper.py` |
