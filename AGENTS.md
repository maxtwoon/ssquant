# AGENTS.md — SSQuant 项目指南

> 本文档面向 AI 编程助手。假设读者对本项目一无所知。
> 项目自然语言为**中文**，所有文档、注释、策略示例、日志输出均使用中文。

---

## 1. 项目概述

**SSQuant（松鼠Quant）** 是一个面向中国期货市场的 CTP 量化交易框架，核心理念是 **"一次编写，三处运行"**：同一份策略代码可在以下三种模式下无修改运行：

- **回测（BACKTEST）**：基于历史 K 线数据的逐 Bar 模拟交易
- **SIMNOW 模拟（SIMNOW）**：连接 CTP 官方模拟环境进行仿真交易
- **实盘交易（REAL_TRADING）**：连接期货公司 CTP 柜台进行真实交易

框架内置 K 线数据自动获取、多品种多周期支持、TICK 流双驱动、智能算法交易（超时撤单/追价重发）、参数优化等功能。

**当前版本**：`0.3.8`  
**Python 版本要求**：`>=3.9, <3.15`  
**操作系统**：仅支持 Windows 10+（CTP 二进制依赖 Windows）  
**开源协议**：Proprietary - Non-Commercial Use Only  
**PyPI**：https://pypi.org/project/ssquant/

---

## 2. 技术栈

| 层级 | 技术/库 |
|------|---------|
| 语言 | Python 3.9 – 3.14 |
| 核心计算 | pandas, numpy, scipy |
| 数据获取 | akshare, requests（远程 API：quant789.com） |
| 可视化 | matplotlib, Pillow |
| CTP 接口 | 各版本编译二进制（`.pyd`/`.dll`/`.so`），按 Python 版本分目录存放 |
| 缠论分析 | czsc（第三方缠论库） |
| 机器学习（可选） | scikit-learn, joblib, statsmodels |
| 数据缓存 | SQLite（`data_cache/kline_data.db`） |
| 测试 | pytest, black, flake8 |

---

## 3. 项目结构

```
ssquant/                        # 项目根目录
├── ssquant/                    # 核心包（pip install 后可用）
│   ├── api/
│   │   └── strategy_api.py     # StrategyAPI：策略唯一交互接口（数据+交易）
│   ├── backtest/
│   │   ├── unified_runner.py   # UnifiedStrategyRunner：三模式统一入口
│   │   ├── backtest_core.py    # MultiSourceBacktester：多品种/多周期回测引擎
│   │   ├── multi_source_backtest.py
│   │   ├── backtest_data.py    # 数据获取与多源对齐
│   │   ├── backtest_results.py # 绩效指标计算
│   │   ├── backtest_report.py  # 报告生成
│   │   ├── backtest_visualization.py # 回测图表绘制
│   │   ├── parameter_optimizer.py    # 网格/随机/贝叶斯/遗传算法参数优化
│   │   ├── live_trading_adapter.py   # 实盘/SIMNOW 适配器（TICK 聚合、持仓追踪、算法交易）
│   │   └── backtest_logger.py
│   ├── config/
│   │   └── trading_config.py   # 中央配置文件（含 API 账号、CTP 账户、默认参数）
│   ├── data/
│   │   ├── api_data_fetcher.py
│   │   ├── local_data_loader.py
│   │   ├── data_source.py      # 单数据源容器，管理待执行订单
│   │   ├── historical_preloader.py
│   │   └── multi_data_fetcher.py
│   ├── ctp/
│   │   ├── loader.py           # CTP 二进制加载器
│   │   ├── py39/ ~ py314/      # 各 Python 版本对应的 CTP 封装文件
│   │   └── __init__.py
│   ├── pyctp/
│   │   ├── simnow_client.py    # SIMNOW 客户端（行情+交易）
│   │   ├── real_trading_client.py
│   │   ├── md_api.py / trader_api.py
│   │   └── simnow_config.py
│   ├── indicators/
│   │   └── tech_indicators.py  # MA, EMA, WMA, MACD, RSI, BOLL 等常用指标
│   └── __init__.py
├── examples/                   # 示例策略（19+ 个），按难度分级
│   ├── A_*.py                  # 工具类（数据导入、撤单重发、穿透式测试）
│   ├── B_*.py                  # 策略类（双均线、海龟、网格、套利、机器学习、缠论等）
│   └── C_*.py                  # 高级类（期权、TICK 高频、限价单 Maker）
├── tests/                      # 测试目录
│   ├── test_chanlun_strategy.py
│   └── test_chanlun_e2e.py
├── data_cache/                 # 运行时数据缓存（SQLite、pickle，默认 gitignore）
├── backtest_results/           # 回测输出图表/CSV/JSON（默认 gitignore）
├── backtest_logs/              # 回测日志（默认 gitignore）
├── docs/                       # 项目内部文档（ADR、代码评审、策略说明）
├── pyproject.toml              # PEP 517 构建配置（setuptools 后端）
├── setup.py                    # 传统 setuptools 配置（与 pyproject.toml 并存）
├── requirements.txt            # 运行时依赖
├── README.md                   # 项目介绍与快速开始
├── 用户手册.md                  # 完整使用教程
├── API参考手册.md               # 所有 API 详细说明
├── 文档导航.md                  # 文档索引与学习路径
├── CLAUDE.md                   # Claude Code 专用指引（命令速查）
└── *.bat                       # Windows 批处理脚本（运行特定回测/策略）
```

---

## 4. 构建与安装命令

### 开发模式安装（推荐）
```bash
pip install -e .
```

### 安装含开发依赖（测试+格式化+Lint）
```bash
pip install -e ".[dev]"
```

### 安装含机器学习依赖
```bash
pip install -e ".[ml]"
```

### 从 PyPI 安装（终端用户）
```bash
pip install ssquant
```

> 注意：当前没有 CI/CD 流水线。发布通过手动打包上传 PyPI 完成。

---

## 5. 测试命令

### 运行全部测试
```bash
pytest
```

### 运行单个测试文件
```bash
pytest tests/test_chanlun_strategy.py
```

### 运行特定测试函数（详细输出）
```bash
pytest tests/test_chanlun_strategy.py::test_kline_to_rawbar -v
```

### 无可视化/无控制台日志模式（适合参数优化或批量测试）
```bash
NO_VISUALIZATION=true NO_CONSOLE_LOG=true pytest
```

### 代码格式化
```bash
black ssquant/ examples/ tests/
```

### 代码检查
```bash
flake8 ssquant/ examples/ tests/
```

---

## 6. 代码风格与开发规范

- **自然语言**：所有代码注释、Docstring、用户文档、日志输出使用**中文**。
- **文件编码**：源码统一使用 `utf-8`，顶部通常有 `# -*- coding: utf-8 -*-` 声明。
- **导入顺序**：标准库 → 第三方库 → 项目内部模块。
- **命名风格**：
  - 类名：`PascalCase`（如 `StrategyAPI`, `UnifiedStrategyRunner`）
  - 函数/变量：`snake_case`（如 `get_close`, `price_tick`）
  - 常量：`UPPER_SNAKE_CASE`（如 `API_USERNAME`, `BACKTEST_DEFAULTS`）
- **策略函数签名**：所有策略必须是接收 `StrategyAPI` 单参数的函数：
  ```python
  def my_strategy(api: StrategyAPI):
      close = api.get_close()
      # ...
  ```
- **示例文件分级**：`A_` 工具、`B_` 策略、`C_` 高级。`examples/` 目录被当作可导入包使用（测试会从中 import）。

---

## 7. 核心架构与数据流

### 7.1 策略 API（`ssquant.api.strategy_api.StrategyAPI`）
策略唯一需要打交道的对象。提供：
- **数据查询**：`get_close()`, `get_open()`, `get_high()`, `get_low()`, `get_volume()`, `get_klines()`, `get_tick()`, `get_ticks()`
- **持仓查询**：`get_pos()`, `get_long_pos()`, `get_short_pos()`, `get_position_detail()`
- **交易操作**：`buy()`, `sell()`, `sellshort()`, `buycover()`, `close_all()`, `reverse_pos()`
- **多数据源**：所有 API 支持 `index=N` 参数访问第 N 个数据源
- **参数与日志**：`get_param()`, `log()`

### 7.2 统一运行器（`UnifiedStrategyRunner`）
根据 `RunMode` 分派到不同引擎：
- `BACKTEST` → `MultiSourceBacktester`
- `SIMNOW` / `REAL_TRADING` → `LiveTradingAdapter` → CTP Client

### 7.3 回测引擎（`MultiSourceBacktester`）
模块化子系统设计：
- `BacktestDataManager`：数据获取、缓存、多源对齐
- `DataSource`：单数据源容器，维护当前索引、持仓、待执行订单
- `BacktestResultCalculator`：收益率、夏普、最大回撤等绩效指标
- `BacktestVisualizer`：matplotlib 资金曲线与信号标注图
- `ParameterOptimizer`：支持网格搜索、随机搜索、贝叶斯优化、遗传算法

### 7.4 实盘适配器（`LiveTradingAdapter`）
- 将 CTP TICK 流实时聚合成 K 线
- 追踪持仓状态（今仓/昨仓、多仓/空仓）
- 智能开平仓拆分（平今优先 / 平昨优先）
- 算法交易：限价单排队 → 超时撤单 → 追价重发
- 异步数据落盘（CSV / SQLite）

### 7.5 CTP 二进制加载（`ssquant.ctp.loader`）
- 按当前 Python 版本（`sys.version_info`）自动加载对应目录下的 `.pyd`/`.dll`
- 版本目录：`py39/`, `py310/`, `py311/`, `py312/`, `py313/`, `py314/`
- 若加载失败，框架回退到仅支持回测模式，打印警告但不崩溃

---

## 8. 配置与安全注意事项

### 8.1 配置文件位置
**`ssquant/config/trading_config.py`** 是中央配置：
- `API_USERNAME` / `API_PASSWORD`：回测数据远程 API 认证（quant789.com）
- `ACCOUNTS`：SIMNOW 和实盘账户字典
- `BACKTEST_DEFAULTS`：回测默认参数（资金、手续费、保证金率等）
- `get_config(mode, ...)`：工厂函数，所有示例统一调用

### 8.2 安全提醒
- **此文件包含敏感凭证**。`.gitignore` 已屏蔽 `*_local.py`, `.env`, `secrets.py` 等模式。
- 修改本地账户信息后**切勿提交**到版本库。
- 实盘交易前必须在 SIMNOW 充分测试（官方建议至少 1 周）。

### 8.3 环境变量
| 变量 | 作用 |
|------|------|
| `NO_VISUALIZATION=true` | 禁止生成回测图表（加速批量运行） |
| `NO_CONSOLE_LOG=true` | 禁止控制台日志输出（减少噪音） |

---

## 9. 部署与运行

### 9.1 回测
```python
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

config = get_config(
    mode=RunMode.BACKTEST,
    symbol='rb888',
    start_date='2025-01-01',
    end_date='2025-11-30',
    kline_period='1h',
    price_tick=1.0,
    contract_multiplier=10,
)
runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
runner.set_config(config)
results = runner.run(strategy=my_strategy)
```

### 9.2 SIMNOW / 实盘
只需将 `mode` 改为 `RunMode.SIMNOW` 或 `RunMode.REAL_TRADING`，并指定 `account='账户名'`。策略代码**完全不变**。

### 9.3 订单类型支持
| 类型 | 回测语义 | 实盘语义 |
|------|---------|---------|
| `bar_close` | 当前 Bar 收盘价成交 | 当前价委托 |
| `next_bar_open` | 下一 Bar 开盘价成交 | 等下一根 K 线 |
| `next_bar_close` / `next_bar_high` / `next_bar_low` | 对应价格成交 | 条件单 |
| `market` | 对手价成交 | 市价/超价委托 |
| `limit` | 回测不支持 | 限价单挂单 |

### 9.4 Windows 批处理脚本
项目中包含 `.bat` 脚本用于快速运行特定策略，例如：
- `运行_缠论5分钟回测.bat` — 运行缠论策略回测
- `setup_and_run.bat` — 组合回测并查看日志尾部

---

## 10. 常见开发注意事项

1. **多数据源支持**：回测和实盘均支持多品种/多周期。回测用 `data_sources=[...]` 配置，实盘同样。策略中通过 `index=0/1/...` 访问。
2. **数据长度检查**：策略开头务必检查数据是否足够，否则可能因索引越界报错。惯例：
   ```python
   if api.get_idx() < 20:
       return
   ```
3. **examples/ 是可导入的**：测试代码会 `from examples.B_缠论多空信号策略 import ...`，因此修改示例文件名或内部接口时需谨慎。
4. **czsc 依赖**：缠论相关策略依赖 `czsc` 库，若未安装会报错。可通过 `pip install czsc` 补充。
5. **无 Docker / 无 Linux CTP**：当前生产环境仅支持 Windows。虽然 `pyproject.toml` 分类器声明了 `Operating System :: Microsoft :: Windows`，但部分 CTP `.so` 文件也开始加入以支持 Linux 回测（实盘仍受限）。
