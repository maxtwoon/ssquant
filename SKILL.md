# SSQuant (松鼠Quant) 框架使用指南

> **Version**: 0.4.5  
> **Purpose**: 让任何 Agent 在阅读本文件后，能够独立编写、修改和运行 SSQuant 量化策略（回测 / SIMNOW 模拟盘 / CTP 实盘）。

## 1. 概述

SSQuant 是一个支持 **"一套代码，三种模式"** 的期货量化交易框架：

- **BACKTEST** — 历史数据回测，生成 HTML 报告和绩效分析
- **SIMNOW** — 连接 SIMNOW 模拟盘，真实 CTP 行情 + 模拟成交
- **REAL_TRADING** — 连接期货公司实盘 CTP，真实资金交易

核心设计哲学：策略代码通过 `StrategyAPI` 与框架交互，无论运行在回测、模拟盘还是实盘，策略逻辑完全一致。

## 2. 环境准备

```python
# 检查 CTP 是否可用（实盘/SIMNOW 需要）
from ssquant import CTP_AVAILABLE
print(CTP_AVAILABLE)  # True / False

# 核心导入（所有策略必备）
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config
import pandas as pd
import numpy as np
```

**Python 版本**: 3.9+ (推荐 Anaconda)  
**操作系统**: Windows 64bit (CTP DLL 限制)  
**安装**: `pip install -e .` (项目根目录有 `pyproject.toml`)

---

## 3. 核心概念

### 3.1 RunMode 枚举

```python
class RunMode(Enum):
    BACKTEST = "backtest"
    SIMNOW = "simnow"
    REAL_TRADING = "real_trading"
```

通过切换 `RUN_MODE` 变量，同一套策略可在三种模式下运行。

### 3.2 StrategyAPI — 策略唯一接口

`StrategyAPI` 是策略与框架交互的唯一接口。框架在运行时注入 `api` 对象，策略通过它访问数据、下单、查询账户。

**上下文结构**（框架自动构建）：

| Key | 含义 |
|-----|------|
| `data` | `MultiDataSource`（回测）或 `LiveDataSource` 列表（实盘） |
| `log` | 日志输出 callable |
| `params` | 用户传入的策略参数字典 |
| `account_info` | 账户信息字典引用 |
| `ctp_client` | CTP 客户端引用（仅实盘模式） |

### 3.3 连续合约映射（888 → 实际合约）

```python
from ssquant.data.contract_mapper import ContractMapper

ContractMapper.is_continuous('rb888')      # True
ContractMapper.is_continuous('rb2601')     # False
ContractMapper.get_continuous_symbol('rb2601')  # 'rb888'
```

- **888** = 主力连续合约
- **777** = 次主力连续合约
- 回测时直接用 `rb888` 拉取连续 K 线数据
- SIMNOW/REAL 模式下，框架自动将 `rb888` 解析为当前实际合约（如 `rb2601`）用于 CTP 订阅和交易

### 3.4 IndicatorCache v2（默认高性能指标系统）

**默认写法**（IndicatorCache v2，O(1) 查询，推荐）：
```python
def initialize(api):
    api.register_indicator('ma20',
        lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
        window=20)

def strategy(api):
    ma20 = api.get_indicator('ma20')              # scalar，O(1)
    arr = api.get_indicator_array('ma20', window=2)  # ndarray[-2], ndarray[-1]
```

**Fallback 写法**（Pandas，仅在指标无法用 `register_indicator` 表达时使用）：
```python
# 仅当遇到动态窗口、实时跨品种复杂计算、非滚动型状态机等无法注册的场景时使用
ma20 = api.get_close().rolling(20).mean().iloc[-1]  # O(N) 每根 K 线
```

**关键区别**：

| 特性 | 默认高性能模式 | Fallback 普通模式 |
|------|-------------|-----------------|
| 计算位置 | `initialize()` 内注册一次 | `strategy()` 内每根 K 线重复计算 |
| 运行时开销 | O(1) ndarray 查找 | O(N) Pandas rolling |
| 回测速度 | **10~30x 提升** | 标准 |
| 多数据源 | 注册时指定 `index=i` | 手动循环 |
| 实盘兼容性 | ✅ 自动重新计算 | ✅ |
| 使用优先级 | **默认优先** | 复杂场景 fallback |

---

## 4. 策略编写规范

### 4.1 必需函数结构

```python
def initialize(api: StrategyAPI):
    """策略初始化，数据加载后、主循环前调用一次"""
    api.log("策略初始化完成")
    # 注册高性能指标、读取参数等

def strategy(api: StrategyAPI):
    """主策略函数，每根 K 线调用一次（tick 模式下每 tick 调用）"""
    # 交易逻辑
    pass

if __name__ == "__main__":
    RUN_MODE = RunMode.BACKTEST
    strategy_params = {'fast_ma': 5, 'slow_ma': 20}

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE, symbol='rb888', ...)
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE, account='simnow_default', ...)
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(RUN_MODE, account='real_default', ...)

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)
    results = runner.run(
        strategy=strategy,
        initialize=initialize,
        strategy_params=strategy_params
    )
```

### 4.2 数据访问 API

**单品种数据访问**：

```python
close = api.get_close()           # pd.Series
open_ = api.get_open()            # pd.Series
high = api.get_high()             # pd.Series
low = api.get_low()               # pd.Series
volume = api.get_volume()         # pd.Series

klines = api.get_klines()         # pd.DataFrame (含 OHLCV)
price = api.get_price()           # scalar，当前价格
idx = api.get_idx()               # int，当前 bar 索引
dt = api.get_datetime()           # datetime，当前 bar 时间

# ndarray 零拷贝访问（高性能）
close_arr = api.get_close_array(window=20)   # np.ndarray
open_arr = api.get_open_array(window=20)
high_arr = api.get_high_array(window=20)
```

**多品种数据访问**（指定 `index=i`）：

```python
ds_count = api.get_data_sources_count()
for i in range(ds_count):
    klines = api.get_klines(i)
    price = api.get_price(i)
    pos = api.get_pos(i)
    api.buy(volume=1, order_type='next_bar_open', index=i)
```

**仓位查询**：

```python
pos = api.get_pos()               # 净仓位 (long - short)
long_pos = api.get_long_pos()     # 多头仓位
short_pos = api.get_short_pos()   # 空头仓位
detail = api.get_position_detail()  # 完整仓位字典
```

**账户查询**：

```python
account = api.get_account()       # 完整账户信息
balance = api.get_balance()       # 权益
available = api.get_available()   # 可用资金
margin = api.get_margin()         # 保证金
commission = api.get_commission() # 手续费
```

### 4.3 交易 API

```python
# 开多
api.buy(volume=1, reason="金叉", order_type='next_bar_open', index=0)

# 平多（volume=None 表示全平）
api.sell(volume=1, reason="死叉", order_type='next_bar_open', index=0)

# 开空
api.sellshort(volume=1, reason="死叉", order_type='next_bar_open', index=0)

# 平空
api.buycover(volume=1, reason="金叉", order_type='next_bar_open', index=0)

# 平仓所有仓位
api.close_all(reason="收盘平仓", order_type='next_bar_open', index=0)

# 反手（平掉当前仓位并反向开仓）
api.reverse_pos(reason="反手", order_type='next_bar_open', index=0)

# 取消所有挂单（仅实盘）
api.cancel_all_orders(index=0)
```

**order_type 说明**：

| 类型 | 回测行为 | 实盘行为 |
|------|---------|---------|
| `'bar_close'` | 当前 bar close 价立即成交 | CTP 市价单（用 bid1/ask1） |
| `'next_bar_open'` | 下一根 bar open 价成交 | CTP 限价单（open 价挂单） |
| `'next_bar_close'` | 下一根 bar close 价成交 | CTP 限价单（close 价挂单） |
| `'next_bar_high'` | 下一根 bar high 价成交 | CTP 限价单（high 价挂单） |
| `'next_bar_low'` | 下一根 bar low 价成交 | CTP 限价单（low 价挂单） |
| `'market'` | 当前 close 价成交 | CTP 市价单 |
| `'limit'` | — | CTP 限价单（需指定 `price`） |

### 4.4 参数系统

```python
# 在 initialize 中读取参数
def initialize(api):
    fast = api.get_param('fast_ma', 10)   # 有默认值
    slow = api.get_param('slow_ma', 20)

# 运行时传入
runner.run(strategy=strategy, strategy_params={'fast_ma': 5, 'slow_ma': 20})
```

---

## 5. 三种运行模式详解

### 5.1 BACKTEST（回测）

```python
config = get_config(RunMode.BACKTEST,
    symbol='rb888',              # 主力连续合约
    kline_period='1h',           # 1m/5m/15m/30m/1h/1d
    adjust_type='1',             # '0'不复权, '1'后复权, '2'前复权
    start_date='2024-01-01',
    end_date='2025-01-01',
    initial_capital=100000,      # 初始资金
    slippage_ticks=1,            # 滑点跳数
    lookback_bars=500,           # K线回溯窗口（IndicatorCache 预热用）
    data_source_mode='data_server',  # 'data_server'(远程,需API账号) 或 'local'(本地SQLite)
    debug=False,
)
```

**多品种回测**：

```python
config = get_config(RunMode.BACKTEST,
    start_date='2025-12-01',
    end_date='2026-01-31',
    initial_capital=100000,
    align_data=False,            # 多品种多周期通常设为 False
    lookback_bars=500,
    data_source_mode='data_server',

    data_sources=[
        {   # 数据源0
            'symbol': 'j888',
            'kline_period': '1m',
            'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
            'slippage_ticks': 1,
            'capital_ratio': 8,       # 资金权重
        },
        {   # 数据源1
            'symbol': 'j888',
            'kline_period': '5m',
            'adjust_type': '1',
            'slippage_ticks': 1,
            'capital_ratio': 1,
        },
    ],
)
```

**⚠️ TICK 回测必须用 `'local'`**：
```python
config = get_config(RunMode.BACKTEST,
    symbol='rb888',
    kline_period='tick',         # TICK 模式
    data_source_mode='local',    # TICK 数据只能用本地 SQLite
    ...
)
```

### 5.2 SIMNOW（模拟盘）

```python
config = get_config(RunMode.SIMNOW,
    account='simnow_default',    # 必须在 trading_config.py 的 ACCOUNTS 中定义
    kline_source='local',        # 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
    server_name='电信1',         # 电信1/电信2/移动/TEST/24hour

    symbol='rb888',
    kline_period='1m',

    order_offset_ticks=10,       # 委托超价跳数
    algo_trading=False,          # 智能算法交易
    order_timeout=10,            # 订单超时（秒）
    retry_limit=3,               # 最大重试次数
    retry_offset_ticks=5,        # 重试超价跳数

    auto_roll_enabled=False,     # 自动移仓
    auto_roll_reopen=True,       # 移仓后补回仓位

    preload_history=True,        # 预加载历史K线
    history_lookback_bars=2000,  # 预加载K线数
    adjust_type='1',             # 复权: '0'不复权, '1'后复权, '2'前复权

    lookback_bars=500,
    enable_tick_callback=False,  # 逐Tick回调（高CPU）
)
```

**SIMNOW 多品种**：
```python
config = get_config(RunMode.SIMNOW,
    account='simnow_default',
    kline_source='local',
    server_name='电信1',

    data_sources=[
        {
            'symbol': 'j888',
            'kline_period': '1m',
            'order_offset_ticks': 10,
            'algo_trading': False,
            'order_timeout': 10,
            'retry_limit': 3,
            'retry_offset_ticks': 5,
            'auto_roll_enabled': False,
            'auto_roll_reopen': True,
            'preload_history': True,
            'history_lookback_bars': 2000,
            'adjust_type': '1',
        },
        # ... 每个数据源独立配置
    ],
)
```

### 5.3 REAL_TRADING（实盘）

```python
config = get_config(RunMode.REAL_TRADING,
    account='real_default',      # 必须在 ACCOUNTS 中填写完整信息
    kline_source='data_server',  # 实盘推荐 data_server（精度更高）

    symbol='rb888',
    kline_period='1m',

    # 实盘配置与 SIMNOW 类似
    order_offset_ticks=10,
    algo_trading=False,
    preload_history=True,
    history_lookback_bars=2000,
    adjust_type='1',
)
```

**实盘账户必需字段**（在 `trading_config.py` 的 `ACCOUNTS['real_default']` 中配置）：

| 字段 | 说明 |
|------|------|
| `broker_id` | 期货公司代码，如 `'9999'` |
| `investor_id` | 资金账号 |
| `password` | 交易密码 |
| `md_server` | 行情前置地址，`tcp://...` |
| `td_server` | 交易前置地址，`tcp://...` |
| `app_id` | 穿透式监管 AppID |
| `auth_code` | 穿透式监管授权码 |

---

## 6. 配置详解

### 6.1 data_sources 参数对照表

| 参数 | BACKTEST | SIMNOW / REAL | 说明 |
|------|----------|---------------|------|
| `symbol` | ✅ | ✅ | 合约代码，如 `'rb888'` |
| `kline_period` | ✅ | ✅ | `1m`/`5m`/`15m`/`30m`/`1h`/`1d`/`tick` |
| `adjust_type` | ✅ | ✅ | `'0'`不复权, `'1'`后复权, `'2'`前复权 |
| `slippage_ticks` | ✅ | ❌ | 回测滑点跳数 |
| `capital_ratio` | ✅ | ❌ | 资金分配权重 |
| `order_offset_ticks` | ❌ | ✅ | 委托超价跳数 |
| `algo_trading` | ❌ | ✅ | 智能算法交易开关 |
| `order_timeout` | ❌ | ✅ | 订单超时（秒） |
| `retry_limit` | ❌ | ✅ | 最大重试次数 |
| `retry_offset_ticks` | ❌ | ✅ | 重试超价跳数 |
| `auto_roll_enabled` | ❌ | ✅ | 自动移仓开关 |
| `auto_roll_reopen` | ❌ | ✅ | 移仓后补回仓位 |
| `preload_history` | ❌ | ✅ | 预加载历史K线 |
| `history_lookback_bars` | ❌ | ✅ | 预加载K线数量 |

### 6.2 回测默认参数

```python
BACKTEST_DEFAULTS = {
    'initial_capital': 20000,
    'commission': 0.0001,        # 万分之一
    'margin_rate': 0.1,          # 10%
    'contract_multiplier': 10,
    'price_tick': 1.0,
    'slippage_ticks': 1,
    'adjust_type': '1',
    'align_data': False,
    'fill_method': 'ffill',
    'lookback_bars': 0,          # 0=不限制
    'data_source_mode': 'data_server',
    'tick_queue_maxsize': 20000,
}
```

### 6.3 自动参数填充

当 `auto_params=True`（默认）时，框架自动查询合约参数：

```python
# 自动填充以下参数：
contract_multiplier   # 合约乘数
price_tick           # 最小变动价位
margin_rate          # 保证金率
commission           # 手续费率（或 commission_per_lot 固定每手）
```

---

## 7. 数据层

### 7.1 SQLite 本地数据库

**数据库位置**: `data_cache/backtest_data.db`

**K-line 表命名**: `{symbol}_{PERIOD}_{adjust_suffix}`

| adjust_type | 后缀 | 示例 |
|-------------|------|------|
| `'0'` | `raw` | `rb888_1M_raw` |
| `'1'` | `hfq` | `rb888_1M_hfq` |
| `'2'` | `qfq` | `rb888_1M_qfq` |

**Tick 表命名**: `{symbol}_tick`（如 `rb888_tick`）

**导入本地数据**（参考 `examples/A_工具_导入数据库DB示例.py`）：

```python
from ssquant.data.local_data_loader import import_kline_data, import_tick_data

# 导入 K-line
import_kline_data(file_path='rb888_1m.csv', symbol='rb888', period='1m', adjust='hfq')

# 导入 Tick
import_tick_data(file_path='rb888_tick.csv', symbol='rb888')
```

### 7.2 本地 vs 远程数据源

| 特性 | `data_source_mode='local'` (回测) / `kline_source='local'` (实盘) | `data_source_mode='data_server'` / `kline_source='data_server'` |
|------|---------------------------------------------------------------|---------------------------------------------------------------|
| 数据来源 | SQLite 本地数据库 | 远程 REST API + WebSocket |
| 认证 | 无需 | 需要 quant789 俱乐部账号 |
| TICK 数据 | ✅ 支持 | ❌ 不支持 |
| K线聚合 | 客户端从 1M 表聚合 | 服务器端聚合 |
| 实时推送 | ❌ 无 | ✅ WebSocket 推送 |
| 离线可用 | ✅ | ❌ |

**⚠️ 关键规则**：
- TICK 回测 **必须** 用 `'local'`
- SIMNOW/REAL 用 `kline_source='local'` 时，框架从本地 SQLite 预加载历史 K 线，然后从 CTP tick 实时合成新 K 线
- 预加载器优先搜索 `{symbol}_{period_upper}_{suffix}`，其次 `{symbol}_{period_lower}_{suffix}`

### 7.3 数据流

**回测模式**：
```
get_config() → UnifiedStrategyRunner → api_data_fetcher → (缓存检查 → API获取) → DataSource.set_data() → 主循环
```

**实盘模式**：
```
get_config() → UnifiedStrategyRunner → CTPClient → HistoricalDataPreloader → LiveDataSource → 策略
         ↓
    CTP tick → 本地K线合成 或 WebSocket data_server 推送
```

---

## 8. 代码模板

### 8.1 最小可运行策略（默认高性能版）

```python
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

def initialize(api: StrategyAPI):
    api.register_indicator('ma20',
        lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
        window=20)

def strategy(api: StrategyAPI):
    close = api.get_close()
    if len(close) < 20:
        return
    ma20 = api.get_indicator('ma20')  # O(1) 查表
    if close.iloc[-1] > ma20 and api.get_pos() <= 0:
        api.buy(volume=1, order_type='next_bar_open')

if __name__ == "__main__":
    config = get_config(RunMode.BACKTEST,
        symbol='rb888', kline_period='1h',
        start_date='2024-01-01', end_date='2025-01-01',
        initial_capital=100000)
    runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
    runner.set_config(config)
    runner.run(strategy=strategy, initialize=initialize)
```

> 所有策略默认必须提供 `initialize()` 注册指标。仅当指标逻辑无法用 `register_indicator` 表达时，才允许在 `strategy()` 内使用 Pandas 计算。

### 8.2 单品种双均线策略（高性能版）

```python
def initialize(api: StrategyAPI):
    fast = api.get_param('fast_ma', 10)
    slow = api.get_param('slow_ma', 20)
    api.register_indicator('ma_fast',
        lambda c, o, h, l, v: pd.Series(c).rolling(fast).mean().to_numpy(),
        window=fast)
    api.register_indicator('ma_slow',
        lambda c, o, h, l, v: pd.Series(c).rolling(slow).mean().to_numpy(),
        window=slow)

def strategy(api: StrategyAPI):
    fast_arr = api.get_indicator_array('ma_fast', window=2)
    slow_arr = api.get_indicator_array('ma_slow', window=2)
    if len(fast_arr) < 2:
        return
    f0, f1 = fast_arr[-2], fast_arr[-1]
    s0, s1 = slow_arr[-2], slow_arr[-1]

    pos = api.get_pos()
    if f0 <= s0 and f1 > s1 and pos <= 0:   # 金叉
        if pos < 0:
            api.buycover(order_type='next_bar_open')
        api.buy(volume=1, order_type='next_bar_open')
    elif f0 >= s0 and f1 < s1 and pos >= 0: # 死叉
        if pos > 0:
            api.sell(order_type='next_bar_open')
        api.sellshort(volume=1, order_type='next_bar_open')
```

### 8.3 策略编写规范（默认高性能写法）

**⚠️ AI 编写策略时，默认使用 IndicatorCache v2 高性能写法。普通 Pandas 写法仅作为无法注册时的 fallback。**

**必读参考**：`examples/B_双均线策略_高性能.py`、`B_海龟交易策略_高性能.py`、`B_多品种多周期交易策略_高性能.py`

#### 核心原理

IndicatorCache v2 将指标计算从 **`strategy()` 内的每根 K 线 O(N)`** 降低到 **`initialize()` 注册后 O(1) 查询`**：

1. `initialize(api)` 中注册指标函数 → 框架在数据加载后**一次性预计算**全部历史
2. `strategy(api)` 中通过 `get_indicator()` / `get_indicator_array()` → **O(1) 直接取值**
3. 实盘模式下，每次新 K 线完成后框架自动触发重计算，策略无需改动

**性能对比（回测）**：

| 指标类型 | Pandas (普通) | ndarray (中档) | IndicatorCache v2 (高性能) |
|---------|--------------|----------------|---------------------------|
| 单 MA | ~5ms/bar | ~0.5ms/bar | ~0.01ms/bar |
| 5 指标 + 4 数据源 | ~80ms/bar | ~8ms/bar | ~0.05ms/bar |

#### 注册指标的标准写法

```python
def initialize(api: StrategyAPI):
    # 从参数读取周期
    fast = api.get_param('fast_ma', 10)
    slow = api.get_param('slow_ma', 20)
    rsi_period = api.get_param('rsi_period', 14)
    boll_period = api.get_param('boll_period', 20)
    atr_period = api.get_param('atr_period', 14)

    # MA
    api.register_indicator('ma_fast',
        lambda c, o, h, l, v: pd.Series(c).rolling(fast).mean().to_numpy(),
        window=fast)
    api.register_indicator('ma_slow',
        lambda c, o, h, l, v: pd.Series(c).rolling(slow).mean().to_numpy(),
        window=slow)

    # EMA
    api.register_indicator('ema_fast',
        lambda c, o, h, l, v: pd.Series(c).ewm(span=fast, adjust=False).mean().to_numpy(),
        window=fast)

    # RSI
    api.register_indicator('rsi',
        lambda c, o, h, l, v: compute_rsi_numpy(c, rsi_period),
        window=rsi_period)

    # 布林带 (upper / middle / lower 分开注册)
    api.register_indicator('boll_mid',
        lambda c, o, h, l, v: pd.Series(c).rolling(boll_period).mean().to_numpy(),
        window=boll_period)
    api.register_indicator('boll_upper',
        lambda c, o, h, l, v: (pd.Series(c).rolling(boll_period).mean() +
                               2 * pd.Series(c).rolling(boll_period).std()).to_numpy(),
        window=boll_period)
    api.register_indicator('boll_lower',
        lambda c, o, h, l, v: (pd.Series(c).rolling(boll_period).mean() -
                               2 * pd.Series(c).rolling(boll_period).std()).to_numpy(),
        window=boll_period)

    # ATR
    api.register_indicator('atr',
        lambda c, o, h, l, v: compute_atr_numpy(h, l, c, atr_period),
        window=atr_period + 1)

    # 唐奇安通道 (海龟策略)
    entry_period = api.get_param('entry_period', 20)
    api.register_indicator('dc_upper',
        lambda c, o, h, l, v: pd.Series(h).rolling(entry_period).max().to_numpy(),
        window=entry_period)
    api.register_indicator('dc_lower',
        lambda c, o, h, l, v: pd.Series(l).rolling(entry_period).min().to_numpy(),
        window=entry_period)
```

**`register_indicator` 参数说明**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `name` | `str` | 指标名称，唯一标识 |
| `func` | `callable` | `func(close, open, high, low, volume) -> np.ndarray` |
| `window` | `int` | 指标所需最小历史长度（用于预热和截断） |
| `index` | `int` | 多数据源时指定数据源索引，默认 `0` |

#### 在 strategy() 中使用指标

```python
def strategy(api: StrategyAPI):
    # 取最近 2 个值用于判断交叉（prev, current）
    fast_arr = api.get_indicator_array('ma_fast', window=2)
    slow_arr = api.get_indicator_array('ma_slow', window=2)
    if len(fast_arr) < 2:
        return
    f0, f1 = fast_arr[-2], fast_arr[-1]   # prev, current
    s0, s1 = slow_arr[-2], slow_arr[-1]

    # 取单个标量值
    rsi_val = api.get_indicator('rsi')           # 当前 bar 的 RSI
    atr_val = api.get_indicator('atr')           # 当前 bar 的 ATR
    boll_up = api.get_indicator('boll_upper')    # 当前 bar 布林上轨

    # 交易逻辑...
```

#### 多品种高性能策略

```python
def initialize(api: StrategyAPI):
    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        period = api.get_param('ma_period', 20)
        api.register_indicator('ma',
            lambda c, o, h, l, v: pd.Series(c).rolling(period).mean().to_numpy(),
            window=period, index=i)

def strategy(api: StrategyAPI):
    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        ma_arr = api.get_indicator_array('ma', window=2, index=i)
        if len(ma_arr) < 2:
            continue
        price = api.get_price(i)
        pos = api.get_pos(i)
        if price > ma_arr[-1] and pos <= 0:
            api.buy(volume=1, order_type='next_bar_open', index=i)
        elif price < ma_arr[-1] and pos >= 0:
            api.sell(volume=1, order_type='next_bar_open', index=i)
```

#### 高性能版本 vs 普通版本的等价性保证

- **交易逻辑必须完全一致**，仅指标获取方式不同
- `get_indicator_array(name, window=2)[-2]` 等价于 Pandas 的 `.iloc[-2]`
- `get_indicator(name)` 等价于 Pandas 的 `.iloc[-1]`
- 已通过 `profiling/audit_examples_equivalence.py` 逐笔对账验证

#### 常见指标辅助函数（建议放在策略文件顶部）

```python
def compute_rsi_numpy(close: np.ndarray, period: int = 14) -> np.ndarray:
    """纯 NumPy RSI 计算，供 register_indicator 使用"""
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(window=period).mean().to_numpy()
    avg_loss = pd.Series(loss).rolling(window=period).mean().to_numpy()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - (100 / (1 + rs))

def compute_atr_numpy(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """纯 NumPy ATR 计算"""
    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(np.maximum(tr1, tr2), tr3)
    return pd.Series(tr).rolling(window=period).mean().to_numpy()
```

#### 高性能策略 checklist

- [ ] `initialize()` 中完成所有 `register_indicator`，不要在 `strategy()` 中计算指标
- [ ] `strategy()` 中只使用 `get_indicator()` / `get_indicator_array()` / `get_xxx_array()`
- [ ] 多品种时通过 `index=i` 为每个数据源独立注册指标
- [ ] `window` 参数必须 ≥ 指标实际所需的最小历史长度
- [ ] 策略逻辑与普通版本保持完全一致（仅替换指标获取方式）
- [ ] 不确定时，打开 `examples/B_xxx_高性能.py` 对照参考

### 8.4 多品种策略模板

```python
def strategy(api: StrategyAPI):
    ds_count = api.get_data_sources_count()
    if not api.require_data_sources(4):
        return

    for i in range(ds_count):
        klines = api.get_klines(i)
        pos = api.get_pos(i)
        # 每个数据源的独立逻辑
        # api.buy(..., index=i)
```

### 8.4 跨品种套利策略

```python
def strategy(api: StrategyAPI):
    j = api.get_klines(0)['close']     # 焦炭
    jm = api.get_klines(1)['close']    # 焦煤
    spread = j - jm
    zscore = (spread - spread.rolling(60).mean()) / spread.rolling(60).std()

    if zscore.iloc[-1] > 2:
        api.sellshort(volume=1, order_type='next_bar_open', index=0)
        api.buy(volume=1, order_type='next_bar_open', index=1)
    elif zscore.iloc[-1] < -2:
        api.buy(volume=1, order_type='next_bar_open', index=0)
        api.sellshort(volume=1, order_type='next_bar_open', index=1)
```

### 8.5 参数优化模板

```python
from ssquant.backtest.backtest_core import MultiSourceBacktester

backtester = MultiSourceBacktester()
backtester.set_base_config({
    'use_cache': True,
    'align_data': False,
    'data_source_mode': 'data_server',
})
backtester.add_symbol_config(symbol='rb888', config={
    'start_date': '2024-01-01', 'end_date': '2025-01-01',
    'initial_capital': 100000,
    'periods': [{'kline_period': '1h', 'adjust_type': '1'}]
})

backtester.preload_data()

param_grid = {'fast_ma': range(5, 21, 5), 'slow_ma': range(20, 61, 10)}
best_params, best_results = backtester.optimize_parameters(
    strategy=strategy, initialize=initialize,
    param_grid=param_grid, method='grid',
    optimization_metric='sharpe_ratio', higher_is_better=True,
    reuse_data=True, parallel=True, n_jobs=4
)
```

---

## 9. 高级功能

### 9.1 自动移仓（Auto Rollover）

仅 SIMNOW/REAL 模式有效：

```python
auto_roll_enabled=True,      # 开启自动移仓
auto_roll_mode='simultaneous',  # 'simultaneous'(平旧+开新同时) 或 'sequential'(等平仓确认)
auto_roll_reopen=True,       # 移仓后在新主力补回仓位
```

### 9.2 智能算法交易（Algo Trading）

```python
algo_trading=True,           # 开启智能算法交易
order_timeout=10,            # 10秒未成交自动撤单
retry_limit=3,               # 最多重试3次
retry_offset_ticks=5,        # 重试时额外超价5跳
```

### 9.3 TICK 数据与逐 Tick 回调

```python
kline_period='tick',         # TICK 模式
enable_tick_callback=True,   # 每收到一个 tick 调用一次 strategy()
tick_callback_interval=0.5,  # tick 回调节流（秒）
tick_queue_maxsize=20000,    # tick 队列大小
```

**⚠️ TICK 回测限制**：
- 回测必须用 `data_source_mode='local'`
- 本地 SQLite 需预先导入 tick 数据
- TICK 模式 CPU 占用高，建议实盘使用 `tick_callback_interval` 节流

### 9.4 订单流与深度数据（data_server 专属）

当 `kline_source='data_server'` 且 data_server 开启对应功能时，K-line DataFrame 包含额外字段：

| 类别 | 字段 |
|------|------|
| 订单流 | `多开`, `空开`, `多平`, `空平`, `双开`, `双平`, `双换`, `B`, `S` |
| 深度数据 | `open_bidp`, `open_askp`, `close_bidp`, `close_askp` |
| 持仓量 | `openint`, `cumulative_openint` |

### 9.5 期权交易

SSQuant 支持 CTP 期权交易：

```python
data_sources=[
    {'symbol': 'au2602C650', 'kline_period': 'tick', 'price_tick': 0.02},  # 看涨期权
    {'symbol': 'au2602P640', 'kline_period': 'tick', 'price_tick': 0.02},  # 看跌期权
    {'symbol': 'au888',      'kline_period': 'tick', 'price_tick': 0.02},  # 标的期货
]
```

---

## 10. 注意事项和最佳实践

### 安全性
- `trading_config.py` 包含 **硬编码的 API 认证信息**，切勿在公共日志中暴露
- CTP 实盘涉及 **真实资金**，务必先在 SIMNOW 验证策略
- 实盘前建议运行 `examples/A_穿透式测试脚本.py` 确认账户连接正常

### 数据一致性
- 回测和实盘的 `symbol`、`kline_period`、`adjust_type` **必须保持一致**，否则本地 SQLite 缓存表名不匹配，导致预加载失败
- 推荐统一使用 `adjust_type='1'`（后复权）
- 高性能版本和普通版本的策略逻辑必须保持一致，仅指标计算方式不同

### 性能优化
- 回测大量数据时，使用 IndicatorCache v2（`register_indicator` + `get_indicator_array`）
- 多品种策略中，`align_data=False` 通常比 `True` 性能更好
- 实盘 tick 回调建议开启节流：`tick_callback_interval=0.5`

### 调试
- `debug=True` — 逐 bar 详细日志
- `SSQUANT_AUDIT_ACCOUNT=1` — 启用账户计算审计
- `SSQUANT_AUDIT_RESULTS=1` — 启用结果对账

### 本地数据库维护
- 定期运行 `examples/A_工具_数据库管理_查看与删除.py` 清理过期数据
- 导入数据前确认 CSV 包含必需字段：`datetime`, `open`, `high`, `low`, `close`, `volume`

### 常见错误
- `kline_source='local'` 但本地无数据 → 运行 `A_工具_导入数据库DB示例.py` 导入
- `data_source_mode='data_server'` 但认证失败 → 检查 `trading_config.py` 中的 `API_USERNAME`/`API_PASSWORD`
- 多品种回测 `align_data=True` 导致数据错位 → 尝试设为 `False`
- 实盘 `order_offset_ticks` 过小导致无法成交 → 适当增大（如 5~10 跳）

---

## 11. 文件索引

| 路径 | 作用 |
|------|------|
| `ssquant/api/strategy_api.py` | StrategyAPI 核心接口 |
| `ssquant/backtest/unified_runner.py` | UnifiedStrategyRunner，三种模式统一入口 |
| `ssquant/backtest/backtest_core.py` | MultiSourceBacktester，回测引擎 |
| `ssquant/backtest/live_trading_adapter.py` | 实盘/SIMNOW 交易桥接（~3400行） |
| `ssquant/data/historical_preloader.py` | 历史数据预加载器 |
| `ssquant/data/api_data_fetcher.py` | REST API 客户端 + SQLite 缓存 |
| `ssquant/data/contract_mapper.py` | 合约代码解析（888/777 检测） |
| `ssquant/config/trading_config.py` | 账户配置、默认参数、API 凭证 |
| `ssquant/config/config_helpers.py` | `get_config()` 配置生成器 |
| `examples/B_双均线策略.py` | 单品种基础策略示例 |
| `examples/B_双均线策略_高性能.py` | IndicatorCache v2 示例 |
| `examples/B_多品种多周期交易策略.py` | 多品种多周期策略示例 |
| `examples/A_工具_导入数据库DB示例.py` | 本地 SQLite 数据导入 |
| `examples/A_穿透式测试脚本.py` | CTP 穿透式测试 |
