# SSQuant - 专业期货 CTP 量化交易框架

SSQuant（松鼠Quant）是面向中国期货市场的 Python 量化交易框架，支持一套策略代码在 **回测 / SIMNOW 仿真 / CTP 实盘** 三种环境中运行。

<<<<<<< HEAD
🐿️ **松鼠Quant** | 专业的期货CTP量化交易框架
<img width="728" height="352" alt="image" src="https://github.com/user-attachments/assets/26201b06-0992-44dd-8416-03edcbb8878b" />
=======
它不是只做历史回测的 toy project，而是围绕期货交易的真实工程问题设计：连续合约、复权、换月、保证金、手续费、滑点、CTP 下单、Tick/K 线数据、SIMNOW 验证、实盘运行和回测报告。
>>>>>>> origin/main

当前版本：v0.4.6
Python：3.9 - 3.14
License：MIT

<<<<<<< HEAD
[GitHub](https://github.com/songshuquant/ssquant) | [Gitee（国内推荐）](https://gitee.com/ssquant/ssquant)

**一次编写，三处运行** - 回测 / SIMNOW模拟 / 实盘CTP

</div>
=======
- GitHub: https://github.com/songshuquant/ssquant
- Gitee: https://gitee.com/ssquant/ssquant
- 官网: https://quant789.com
>>>>>>> origin/main

---

## 一句话理解

SSQuant 的核心目标是：

> 让期货策略从研究、回测、仿真到实盘尽量使用同一套代码和同一套交易接口。

策略只和 `StrategyAPI` 交互：

<<<<<<< HEAD
- **自动开平仓管理** - 智能识别开平仓、今昨仓
- **智能算法交易** - 支持限价单排队、超时撤单、追价重发等高级逻辑
- **实时回调系统** - on_trade/on_order/on_cancel 实时通知
- **TICK流双驱动** - K线驱动 + TICK驱动两种模式

### ✅ 丰富的策略示例

- 19个完整策略示例
- 涵盖趋势、套利、轮动、期权、机器学习等类型
- 从入门到高级，循序渐进

---

## 🖥️ 系统要求

| 项目 | 要求 |
|------|------|
| **操作系统** | Windows 10+（⚠️ 目前仅支持 Windows，Linux 版本待更新） |
| **Python** | 3.9 ~ 3.14 |
| **CTP版本** | 6.7.7 ~ 6.7.10 |
| **内存** | 4GB+ |

---

## ⚡ 快速开始

### 1. 安装

#### 方式一：使用 pip 安装（推荐）

```bash
pip install ssquant
```

> 💡 **新手安装指引 (解决环境问题)**
> 
> 如果遇到环境索引问题，请按以下步骤操作：
> 1. **卸载旧版本**：`pip uninstall ssquant`
> 2. **重新安装**（推荐使用国内源）：
>    ```bash
>    pip install ssquant -i https://pypi.tuna.tsinghua.edu.cn/simple
>    ```
> 3. **获取示例**：新手朋友直接通过 pip 安装框架，然后到 [GitHub](https://github.com/songshuquant/ssquant) 或 [Gitee（国内推荐）](https://gitee.com/ssquant/ssquant) 下载 `examples/` 目录下的策略示例。
> 4. **补充依赖**：运行中如果提示缺什么库，直接 `pip install 库名` 安装即可。

#### 方式二：从 GitHub/Gitee 源码安装

如果您下载了源码压缩包（通常解压后文件夹名为 `ssquant-main`），或者通过 git clone 拉取了代码：

1. 打开终端（CMD/PowerShell），进入该文件夹（确保能看到 `setup.py` 文件）。
2. 运行安装命令：
=======
```python
api.buy()
api.sell()
api.sellshort()
api.buycover()
api.close_all()
```

运行环境由 `RunMode` 决定：

```python
RunMode.BACKTEST       # 回测
RunMode.SIMNOW         # SIMNOW 仿真
RunMode.REAL_TRADING   # CTP 实盘
```

---

## 核心能力

| 能力 | 说明 |
|---|---|
| 一套代码三处运行 | 回测、SIMNOW、实盘共享策略主体 |
| StrategyAPI | 策略唯一数据和交易入口 |
| 高性能回测 | ndarray 缓存 + IndicatorCache v2 |
| 本地/远程数据 | 支持 `data_server` 和 `local` 两种模式 |
| 连续合约 | 支持 `888` 主力、`777` 次主力 |
| 复权处理 | 支持不复权、后复权、前复权 |
| 价格双轨制 | 复权策略价映射真实价格，用真实价格计算回测指标 |
| 自动移仓 | 支持主力换月平旧开新 |
| 交互式报告 | HTML K 线图、交易标记、综合绩效、费用统计 |
| AI Agent | 自然语言生成、修改、运行和迭代策略 |

---

## v0.4.6 最重要的变化

v0.4.6 的关键变化不是新增一个普通功能，而是建立价格双轨制：策略使用复权价格保持连续性，回测指标通过映射后的真实价格计算。

过去，策略使用后复权/前复权连续合约时，复权价格既用于指标，也可能进入成交、盯市和权益曲线计算。这样会让换月点附近的盈亏被复权因子污染。

v0.4.6 改为价格双轨体系：

| 价格 | 用途 |
|---|---|
| `price` / `current_price` | 策略看到的复权价，用于指标、信号、图表 |
| `raw_price` / `current_raw_price` | 由复权价映射回的真实价格，用于回测指标、持仓盯市、权益曲线 |

这意味着：

- 策略仍然可以用连续平滑的复权价格做技术指标。
- 回测指标通过映射后的真实价格计算。
- 后复权/前复权回测结果可能和 v0.4.5 不一致，这是预期修正。

详细更新见 [046.MD](046.MD)。

---

## 安装

正式安装请使用源码仓库。PyPI 只保留弃用提示包，不再作为真实安装入口。

### GitHub
>>>>>>> origin/main

```bash
pip install -e .
```

<<<<<<< HEAD
> **注意**：
> - 命令最后有一个点 `.`，代表当前目录，不要漏掉。
> - 文件夹名字（如 `ssquant-main`）不影响安装，只要目录结构正确即可。

#### ❓ 常见问题：ModuleNotFoundError: No module named 'ssquant'

如果运行策略时遇到这个错误：

```
ModuleNotFoundError: No module named 'ssquant'
```

**原因**：ssquant 未安装或已被卸载。

**解决方法**：

1. 检查是否已安装：
   ```bash
   pip list | findstr ssquant   # Windows
   ```

2. 如果没有找到，重新安装：
   ```bash
   # 方式一：从 PyPI 安装
   pip install ssquant
   
   # 方式二：从源码安装（在项目目录下执行）
   pip install -e .
   ```

3. 验证安装成功：
   ```bash
   python -c "from ssquant.api.strategy_api import StrategyAPI; print('ssquant 导入成功!')"
   ```

### 2. 配置账户

安装完成后，需要配置相关账户信息。编辑 `ssquant/config/trading_config.py`：

#### 📊 数据API配置（回测必需）

框架使用**松鼠俱乐部会员远程数据库**，会员填入账号密码后，回测和实盘自动预拉取数据到本地：

```python
# ========== 数据API认证 (松鼠俱乐部会员) ==========
API_USERNAME = "你的会员账号"
API_PASSWORD = "你的会员密码"
```

> 💡 **非会员用户**：
> - 可自行修改远程服务器地址
> - 或参考 `examples/A_工具_导入数据库DB示例.py` 导入本地数据

#### 🔐 交易账户配置（模拟/实盘）

```python
# SIMNOW账户（模拟交易）
ACCOUNTS = {
    'simnow_default': {
        'investor_id': '你的SIMNOW账号',
        'password': '你的密码',
        'server_name': '电信1',  # 电信1/电信2/移动/TEST
        # ...
    },
    
    # 实盘账户
    'real_default': {
        'broker_id': '期货公司代码',
        'investor_id': '资金账号',
        'password': '密码',
        'md_server': 'tcp://xxx:port',
        'td_server': 'tcp://xxx:port',
        'app_id': 'AppID',
        'auth_code': '授权码',
        # ...
    },
}
```

### 3. 编写策略
=======
### Gitee

```bash
git clone https://gitee.com/ssquant/ssquant.git
cd ssquant
pip install -e .
```

安装后，如果出现 `ModuleNotFoundError: No module named 'ssquant'`，通常是没有在项目根目录执行 editable install，或误装了 PyPI redirect 包：

```bash
pip uninstall ssquant
pip install -e .
```

---

## 数据模式

SSQuant 支持两种数据模式。

### 远程数据：`data_source_mode='data_server'`

适合 quant789 松鼠俱乐部会员使用。

特点：

- 远程服务器维护历史 K 线和实时 K 线。
- 回测、SIMNOW、实盘预加载可直接拉取数据。
- 支持多周期 K 线、订单流和盘口深度数据。
- 免去本地导入和维护数据的成本。

示例：
>>>>>>> origin/main

```python
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="15m",
    data_source_mode="data_server",
)
```

需要在 `ssquant/config/trading_config.py` 中配置远程数据账号：

```python
API_USERNAME = "你的账号"
API_PASSWORD = "你的密码"
```

### 本地数据：`data_source_mode='local'`

本地模式不需要会员账号，适合离线回测、私有数据和 Tick 回测。

特点：

- 数据保存在本地 SQLite。
- 支持 CSV、Excel、JSON、Parquet、Feather、Pickle 导入。
- Tick 回测必须使用本地模式。
- 导入 1 分钟 K 线后可派生 5m、15m、1h、1d 等周期。
- SIMNOW/实盘可通过 CTP Tick 落盘，逐步积累自己的本地行情库。

示例：

```python
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="15m",
    data_source_mode="local",
)
```

导入本地数据：

```bash
python examples/A_工具_导入数据库DB示例.py
```

---

## 第一个策略

下面是一个最小高性能双均线思路示例。它使用 `initialize(api)` 注册指标，在 `strategy(api)` 中 O(1) 查询。

```python
import pandas as pd
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config


def initialize(api: StrategyAPI):
    api.register_indicator(
        "ma20",
        lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
        window=20,
    )


def strategy(api: StrategyAPI):
    price = api.get_price()
    ma20 = api.get_indicator("ma20")

    if pd.isna(ma20):
        return

    if price > ma20 and api.get_pos() <= 0:
        api.buy(volume=1, order_type="next_bar_open", reason="上穿 MA20")
    elif price < ma20 and api.get_pos() > 0:
        api.sell(order_type="next_bar_open", reason="下穿 MA20")


if __name__ == "__main__":
    config = get_config(
        RunMode.BACKTEST,
        symbol="rb888",
        kline_period="1h",
        start_date="2024-01-01",
        end_date="2025-01-01",
        adjust_type="1",
        data_source_mode="data_server",
        initial_capital=100000,
    )

    runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
    runner.set_config(config)
    runner.run(strategy=strategy, initialize=initialize)
```

<<<<<<< HEAD
### 4. 切换模式只需改配置
=======
---

## 三模式切换

策略函数不需要因为运行环境变化而重写。通常只切换 `RunMode` 和配置。
>>>>>>> origin/main

```python
# 回测
config = get_config(
    RunMode.BACKTEST,
    symbol="rb888",
    kline_period="1h",
    start_date="2024-01-01",
    end_date="2025-01-01",
)

# SIMNOW 仿真
config = get_config(
    RunMode.SIMNOW,
    account="simnow_default",
    symbol="rb888",
    kline_period="5m",
)

# CTP 实盘
config = get_config(
    RunMode.REAL_TRADING,
    account="real_default",
    symbol="rb888",
    kline_period="5m",
)
```

实盘策略建议捕获关键异常，避免单根 K 线错误导致整个交易进程退出。

---

## StrategyAPI 约定

<<<<<<< HEAD
| 文档 | 说明 | 适合 |
|------|------|------|
| [用户手册.md](用户手册.md) | 📖 完整使用教程 | 新手必读 |
| [API参考手册.md](API参考手册.md) | 📚 详细API说明 | 开发查询 |
| [文档导航.md](文档导航.md) | 📑 所有文档索引 | 查找文档 |
---

## 🎓 示例策略

所有示例在 `examples/` 目录（共19个）：

### 工具类 (A_开头)

| 文件 | 说明 |
|------|------|
| `A_工具_导入数据库DB示例.py` | 数据导入数据库 |
| `A_工具_数据库管理_查看与删除.py` | 数据库管理 |
| `A_撤单重发示例.py` | 订单撤单重发机制 |
| `A_穿透式测试脚本.py` | CTP穿透式认证测试 |

### 策略类 (B_开头)

| 文件 | 说明 |
|------|------|
| `B_双均线策略.py` | ⭐ 经典均线交叉，入门推荐 |
| `B_海龟交易策略.py` | 唐奇安通道突破 |
| `B_十大经典策略之Aberration.py` | 布林带突破 |
| `B_日内交易策略.py` | 日内交易 |
| `B_网格交易策略.py` | 网格交易 |
| `B_强弱截面轮动策略.py` | 多品种强弱轮动 |
| `B_跨周期过滤策略.py` | 多周期信号过滤 |
| `B_跨品种套利策略.py` | 品种间价差套利 |
| `B_跨期套利策略.py` | 同品种跨期套利 |
| `B_多品种多周期交易策略.py` | 多品种多周期 |
| `B_多品种多周期交易策略_参数优化.py` | 参数优化示例 |
| `B_机器学习策略_随机森林.py` | ML机器学习预测 |

### 高级类 (C_开头)

| 文件 | 说明 |
|------|------|
| `C_期权交易策略.py` | 期权交易 |
| `C_期货期权组合策略.py` | 期货期权组合 |
| `C_纯Tick高频交易策略.py` | TICK流高频交易 |

---

## 🏗️ 项目结构

```
ssquant/
├── api/                    # 策略API
│   └── strategy_api.py     # 核心API类
├── backtest/               # 回测引擎
│   ├── unified_runner.py   # 统一运行器
│   ├── backtest_core.py    # 回测核心
│   └── live_trading_adapter.py  # 实盘适配器
├── config/                 # 配置管理
│   └── trading_config.py   # 配置生成（账户配置在此）
├── data/                   # 数据管理
│   ├── api_data_fetcher.py # API数据获取
│   └── local_data_loader.py # 本地数据加载
├── ctp/                    # CTP二进制文件
│   ├── py39/ ~ py314/      # 各Python版本的CTP文件
│   └── loader.py           # CTP加载器
├── pyctp/                  # CTP封装
│   ├── simnow_client.py    # SIMNOW客户端
│   └── real_trading_client.py  # 实盘客户端
└── indicators/             # 技术指标
    └── tech_indicators.py
```

---

## 💡 核心API

### 数据获取
=======
策略必须通过 `StrategyAPI` 交易。不要在策略里直接操作底层 CTP 接口。

### 交易接口
>>>>>>> origin/main

```python
api.buy(volume=1)        # 开多
api.sell(volume=1)       # 平多
api.sellshort(volume=1)  # 开空
api.buycover(volume=1)   # 平空
api.close_all()          # 全部平仓
```

### 数据接口

```python
api.get_price()
api.get_open()
api.get_high()
api.get_low()
api.get_close()
api.get_volume()
api.get_pos()
api.get_balance()
```

### 高性能指标接口

```python
api.register_indicator(name, func, window=None, index=0)
api.get_indicator(name, index=0)
api.get_indicator_array(name, window=None, index=0)
api.get_close_array(window=None, index=0)
```

AI 生成策略时，默认应该：

- 写 `initialize(api)`。
- 在 `initialize(api)` 中注册指标。
- 在 `strategy(api)` 中只做 O(1) 查询。
- 仅当指标逻辑无法预注册时，才回退到 Pandas 普通写法。

---

## 连续合约与复权

SSQuant 常用连续合约约定：

| 后缀 | 含义 |
|---|---|
| `888` | 主力连续 |
| `777` | 次主力连续 |

复权类型：

| 参数 | 含义 |
|---|---|
| `adjust_type="0"` | 不复权 |
| `adjust_type="1"` | 后复权 |
| `adjust_type="2"` | 前复权 |

v0.4.6 起，复权只影响策略看到的价格连续性，不再污染真实盈亏统计。报告中如果复权价和真实价不同，交易表格会显示实际成交价，方便对账。

---

## 回测报告

回测结束后，框架会输出文本报告和 HTML 交互式报告。

HTML 报告包含：

- 资金曲线和利润曲线。
- 回撤曲线。
- K 线/Tick 图。
- 交易标记。
- 手续费、滑点、交易盈亏、净利润。
- 多数据源综合页。
- 交易记录筛选和分页。
- 复权价与真实价对照显示。

v0.4.6 的综合最大回撤基于综合权益曲线计算，而不是简单取单品种平均。

---

## AI Agent

`ai_agent/` 是 SSQuant 的 AI 策略助手，可以通过自然语言生成、修改、运行和分析策略。

安装依赖：

```powershell
cd ai_agent
pip install -r requirements.txt
```

启动：

```powershell
python start_server.py
```

访问：

```text
http://localhost:5000
```

v0.4.6 起，AI Agent 使用 waitress 生产服务器启动，不建议长期使用 Flask 开发服务器。

主要能力：

- OpenAI 兼容模型。
- Claude 原生 API。
- DeepSeek-R1 / Claude thinking 思考内容展示。
- 图片和文本附件上传。
- 自动运行、自动调试、自动迭代。
- 强制停止运行中的策略进程。
- 工作区、报告和策略历史管理。

升级 AI Agent 时请注意：`settings.json`、`history.json`、`workspaces/`、`strategies/` 是运行数据，不建议直接覆盖。

---

## 推荐示例

`examples/` 是 SSQuant 最重要的上手保障之一。

新手不要一开始就让 AI 从零写复杂策略。正确顺序是：

1. 先安装框架。
2. 先导入或配置好数据。
3. 先跑通 `examples/` 中最接近自己需求的示例策略。
4. 再在示例基础上改参数、改信号、改仓位管理。
5. 最后再让 AI 帮你扩展成自己的策略。

这些示例不是装饰文件，而是框架能力的可运行样板。它们覆盖了期货市场中大约 80% 常见策略类型：趋势跟踪、均值回归、网格、套利、跨周期过滤、截面轮动、机器学习、加减仓、正反手、Tick 高频、期权组合、订单流、自动换月和数据工具。

对新手来说，跑通示例有三个作用：

- 验证安装、数据、账号、报告生成是否正常。
- 学会 SSQuant 的标准策略结构和 `StrategyAPI` 用法。
- 给 AI 一个可靠模板，避免生成不符合框架约定的代码。

### 示例分类

| 示例 | 用途 |
|---|---|
| `examples/A_工具_导入数据库DB示例.py` | 本地数据导入，local 模式第一步 |
| `examples/A_工具_数据库管理_查看与删除.py` | 查看和清理本地 SQLite 数据 |
| `examples/A_CTP连接状态监测测试_真实断网.py` | CTP 连接状态和断网恢复测试 |
| `examples/A_撤单重发示例.py` | 撤单、重发、追单链路示例 |
| `examples/A_穿透式测试脚本.py` | CTP 穿透式监管相关测试 |
| `examples/B_双均线策略_高性能.py` | 高性能策略入门 |
| `examples/B_海龟交易策略_高性能.py` | 唐奇安通道策略 |
| `examples/B_十大经典策略之Aberration_高性能.py` | 经典通道突破策略 |
| `examples/B_日内交易策略.py` | 日内交易模板 |
| `examples/B_网格交易策略.py` | 网格交易 |
| `examples/B_加仓策略_高性能.py` | 趋势加仓 |
| `examples/B_减仓策略_高性能.py` | 分批减仓 |
| `examples/B_正反手策略_高性能.py` | 多空反转 |
| `examples/B_正反手混合开平仓策略_高性能.py` | 正反手与混合开平仓 |
| `examples/B_多品种多周期交易策略_高性能.py` | 多品种、多周期 |
| `examples/B_自动参数示例.py` | 参数优化 |
| `examples/B_多品种多周期交易策略_参数优化.py` | 多品种多周期参数优化 |
| `examples/B_自动换月示例.py` | 主力连续合约自动换月 |
| `examples/B_跨周期过滤策略_高性能.py` | 大周期过滤小周期交易 |
| `examples/B_跨品种套利策略_高性能.py` | 跨品种套利 |
| `examples/B_跨期套利策略_高性能.py` | 跨期套利 |
| `examples/B_强弱截面轮动策略_高性能.py` | 截面强弱轮动 |
| `examples/B_机器学习策略_随机森林_高性能.py` | 机器学习策略 |
| `examples/C_纯Tick高频交易策略.py` | Tick 回测 |
| `examples/C_纯Tick限价单交易策略.py` | Tick 限价单交易 |
| `examples/C_期权交易策略.py` | 期权交易 |
| `examples/C_期货期权组合策略.py` | 期货期权组合 |
| `examples/D_订单流与深度数据_data_server模式.py` | 订单流和深度数据 |

### 推荐阅读顺序

如果你是第一次使用 SSQuant，建议按这个顺序：

1. `A_工具_导入数据库DB示例.py`
2. `B_双均线策略_高性能.py`
3. `B_海龟交易策略_高性能.py`
4. `B_多品种多周期交易策略_高性能.py`
5. `B_自动参数示例.py`
6. 再根据自己的方向选择套利、Tick、期权、机器学习或订单流示例。

所有生产策略建议优先参考 `*_高性能.py` 写法。

AI 生成策略时，也应该优先模仿这些示例的结构：`initialize(api)` 注册指标，`strategy(api)` 中 O(1) 查询，交易只通过 `StrategyAPI` 完成。

---

## 关键文件

| 需求 | 文件 |
|---|---|
| 策略 API | `ssquant/api/strategy_api.py` |
| 回测主循环 | `ssquant/backtest/backtest_core.py` |
| 三模式统一入口 | `ssquant/backtest/unified_runner.py` |
| 实盘/SIMNOW 桥接 | `ssquant/backtest/live_trading_adapter.py` |
| 数据源 | `ssquant/data/data_source.py` |
| 远程数据和缓存 | `ssquant/data/api_data_fetcher.py` |
| 本地复权 | `ssquant/data/local_adjust.py` |
| 配置生成 | `ssquant/config/config_helpers.py` |
| 默认配置 | `ssquant/config/trading_config.py` |
| AI Agent | `ai_agent/` |
| v0.4.6 更新日志 | `046.MD` |

---

## 升级到 v0.4.6

建议分阶段升级：

1. 先替换 `ssquant/`。
2. 跑不复权回测，确认结果基本稳定。
3. 跑后复权/前复权连续合约回测，确认报告中有 `raw_price` 映射真实价。
4. 再替换 AI Agent 代码。
5. 备份并合并 `ai_agent/settings.json`、`history.json`、`workspaces/`、`strategies/`。

重点验证：

- 不复权回测。
- 复权连续合约回测。
- 多品种多周期回测。
- HTML 报告。
- SIMNOW/实盘平今平昨。
- AI Agent `python start_server.py`。

---

## 常见问题

### 回测没有数据

检查：

- `data_source_mode` 是否正确。
- 远程模式账号是否配置。
- 本地模式是否已经导入数据。
- 合约、周期、日期范围是否存在数据。

### Tick 回测为什么报错

Tick 回测必须使用：

```python
data_source_mode="local"
```

### 复权回测结果为什么和 v0.4.5 不一样

v0.4.6 通过价格双轨制把复权价映射回真实价格，并用真实价格计算回测指标，这是预期修正。

### AI Agent 为什么要用 `start_server.py`

`start_server.py` 使用 waitress，能改善 Windows 下长时间运行、后台切换和 SSE 连接不稳定的问题。

---

## 许可证与风险提示

<<<<<<< HEAD
- **Python**: 3.9 ~ 3.14
- **系统**: Windows 10+（⚠️ 目前仅支持 Windows，Linux 版本待更新）
- **内存**: 4GB+
- **网络**: 稳定连接（实盘/SIMNOW）

### CTP版本支持

框架内置 CTP 6.7.7 ~ 6.7.10 版本，位于 `ssquant/ctp/pyXXX/` 目录：

| Python版本 | 目录 | 状态 |
|-----------|------|------|
| 3.9 | `py39/` | ✅ 已包含 |
| 3.10 | `py310/` | ✅ 已包含 |
| 3.11 | `py311/` | ✅ 已包含 |
| 3.12 | `py312/` | ✅ 已包含 |
| 3.13 | `py313/` | ✅ 已包含 |
| 3.14 | `py314/` | ✅ 已包含 |

---

## ⚠️ 风险提示

本框架仅供学习和研究使用。期货交易有风险，入市需谨慎。

- ⚠️ 请先在SIMNOW充分测试（至少1周）
- ⚠️ 实盘前用小资金验证
- ⚠️ 做好风险管理和止损
- ⚠️ 不要使用高杠杆

---

## 📖 快速链接

- [PyPI 主页](https://pypi.org/project/ssquant/) - 安装和版本信息
- [GitHub 仓库](https://github.com/songshuquant/ssquant) - 源码和问题反馈
- [Gitee 仓库](https://gitee.com/ssquant/ssquant) - 国内推荐，访问更快
- [用户手册](用户手册.md) - 完整使用教程
- [API参考](API参考手册.md) - 所有API详解

---

## 📝 更新日志

### v0.3.7 (2025-12)

- 🔄 移除构建脚本和冗余文件
- ✅ 修复 CTP 登录报错乱码问题
- ✅ 优化项目结构

### v0.3.6 (2025-12)

- ✅ 修复 CTP 登录报错乱码问题 (Windows下GBK/GB18030解码)
- ✅ 优化 SIMNOW 和实盘客户端的错误信息显示

### v0.3.0 (2025-12)

- ✅ 完整的TICK流双驱动模式
- ✅ 多品种多周期支持
- ✅ 订单撤单重发机制
- ✅ 实时回调系统（on_trade/on_order/on_cancel）
- ✅ 动态price_tick和offset_ticks
- ✅ 统一的API接口
- ✅ 19个策略示例

---

**开始你的量化交易之旅！** 🚀

查看 [用户手册.md](https://github.com/songshuquant/ssquant/blob/main/%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C.md) 了解详细使用方法。
=======
SSQuant 使用 MIT License。

期货交易具有高风险。SSQuant 是研究和工程框架，不构成投资建议。实盘前请充分回测和 SIMNOW 验证，并从小资金开始。
>>>>>>> origin/main
