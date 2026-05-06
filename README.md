# SSQuant — 期货量化交易框架

<div align="center">

🐿️ **松鼠Quant** | 专业期货 CTP 量化交易框架（回测 / SIMNOW / 实盘）

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux-lightgrey.svg)]()
[![Version](https://img.shields.io/badge/版本-0.4.5-brightgreen.svg)](045.MD)

[GitHub](https://github.com/songshuquant/ssquant) | [Gitee](https://gitee.com/ssquant/ssquant) | [主页 quant789.com](https://quant789.com)

**一次编写，三处运行**

> 关注公众号 **松鼠Quant**，获取量化策略、框架更新与会员服务

</div>

---

## 🚀 v0.4.5 核心亮点

### 回测速度 30×–100× 提升

v0.4.5 对回测引擎进行全链路热点消除，引入 **三层性能档位**：

| 档位 | 典型提速 | 用法 |
|------|---------|------|
| **Pandas 普通档** | 基准 1× | `api.get_close().rolling(20).mean()` |
| **ndarray 中档** | **5×–10×** | `api.get_close_array(window=20)` |
| **IndicatorCache v2** | **30×–100×** | `api.register_indicator()` + `api.get_indicator()` |

底层通过 **ndarray 价格缓存**、**增量账户状态**、**per-Bar K线缓存**、`__slots__` **权益曲线纯对象**、**指标预计算** 等 7 大工程优化，实现数量级飞跃。

```python
def initialize(api):
    # 注册一次，全量预计算
    api.register_indicator('ma20',
        lambda c, o, h, l, v: pd.Series(c).rolling(20).mean().to_numpy(),
        window=20)

def strategy(api):
    # O(1) 查表，零 Pandas 开销
    ma20 = api.get_indicator('ma20')
```

> 同一套代码回测/SIMNOW/实盘通用，数值逐位等价。详见 [045.MD](045.MD)。

### 数据模式：远程 vs 本地

SSQuant 支持两种数据源，满足不同用户需求：

#### 🔷 远程模式（`data_source_mode='data_server'`）— 推荐

**面向 [quant789.com](https://quant789.com) 松鼠俱乐部会员。**

- **数据最新**：服务器维护全品种历史 + 实时 K 线，回测和实盘预加载直接拉取最新数据
- **免维护**：无需手动导入 CSV，一键回测任意品种任意周期
- **服务器聚合**：1M/5M/15M/1H/1D 等任意周期由服务端直接推送，无需本地派生
- **订单流深度数据**：支持 `多开/空开/多平/空平/双开/双平` 等 12+ 订单流字段 + 盘口深度数据
- **WebSocket 实时推送**：SIMNOW/实盘连接后毫秒级接收新 K 线

```python
config = get_config(RunMode.BACKTEST,
    symbol='rb888',
    data_source_mode='data_server',  # 默认即远程，可不填
)
```
首次使用需在 `ssquant/config/trading_config.py` 填写俱乐部账号：
```python
API_USERNAME = "你的俱乐部手机号或邮箱"
API_PASSWORD = "你的俱乐部密码"
```
> 非会员可访问 [quant789.com](https://quant789.com) 或关注公众号 **松鼠Quant** 申请加入。

---

#### 🔶 本地模式（`data_source_mode='local'`）

**无需会员，完全免费，数据自主可控。**

- **零成本**：免会员、免联网（导入后即可离线运行）
- **TICK 支持**：TICK 回测唯一选择，支持逐笔数据导入
- **隐私安全**：数据完全留在本地磁盘，策略源码与数据不出境
- **本地 K 线聚合**：导入 1 分钟数据后，框架自动派生 5M/15M/30M/1H/1D 等任意周期，无需重复导入
- **CTP 落盘**：实盘/SIMNOW 模式下，框架通过 CTP 接收 Tick，实时合成 K 线并落盘到本地 SQLite，形成你的私有行情库

```python
config = get_config(RunMode.BACKTEST,
    symbol='rb888',
    data_source_mode='local',
)
```

**支持导入的数据格式**：

| 格式 | 扩展名 | 说明 |
|------|--------|------|
| CSV | `.csv` | 最常用，Excel 另存为 CSV 即可 |
| Excel | `.xlsx` / `.xls` | 直接读取多 Sheet 文件 |
| JSON | `.json` | 结构化数据，适合程序化生成 |
| Parquet | `.parquet` | 列式存储，读取极快，适合大数据量 |
| Feather | `.feather` | Apache Arrow 格式，跨语言零拷贝 |
| Pickle | `.pkl` / `.pickle` | Python 原生序列化，DataFrame 直存 |

**数据字段要求（K 线）**：

导入文件必须包含以下列（列名不区分大小写）：
- `datetime` — 时间戳（如 `2024-01-01 09:00:00`）
- `open` — 开盘价
- `high` — 最高价
- `low` — 最低价
- `close` — 收盘价
- `volume` — 成交量

可选列：`open_interest`（持仓量）、`amount`（成交额）等。

**数据字段要求（TICK）**：

TICK 回测需包含：
- `datetime` — 时间戳（含毫秒）
- `LastPrice` — 最新价
- `Volume` — 累计成交量
- `BidPrice1` / `AskPrice1` — 买一卖一价
- `BidVolume1` / `AskVolume1` — 买一卖一量

**导入示例**：

```bash
python examples/A_工具_导入数据库DB示例.py
```

运行后按提示选择文件格式、文件路径、品种代码（如 `rb888`）、周期（`1m`/`tick`）、复权方式（`raw`/`hfq`/`qfq`），数据自动写入 `data_cache/backtest_data.db`。

**表名格式**：`{symbol}_{period}_{adjust}`  
**示例**：`rb888_1M_hfq`（螺纹钢主力连续，1分钟，后复权）

**本地 K 线聚合**：

只需导入 **1 分钟 K 线**，框架在回测时自动通过 `ssquant/data/multi_period.py` 本地聚合为任意目标周期：

```python
# 只导入了 rb888 的 1M 数据
config = get_config(RunMode.BACKTEST,
    symbol='rb888',
    kline_period='15m',        # ← 框架自动从 1M 聚合为 15M
    data_source_mode='local',
)
```

支持的派生周期：`1m` `2m` `3m` `5m` `10m` `15m` `30m` `1h` `2h` `4h` `1d` `1w` 等。

**CTP 通道落盘（实盘/SIMNOW）**：

本地模式不仅用于回测。在 SIMNOW / 实盘模式下，框架通过 CTP 接收交易所原始 Tick：

1. **Tick 实时入队** → CTP 回调将 Tick 写入有界队列
2. **本地 K 线合成** → `multi_period.py` 按时间切片聚合为 1M/5M 等周期
3. **SQLite 落盘** → 新 K 线落成后自动写入 `data_cache/backtest_data.db`
4. **历史预加载** → 下次启动时直接从本地 SQLite 预加载，无需重复拉取

这意味着：**跑一段时间实盘后，你的本地数据库会自动积累历史 K 线，回测时可直接复用。**

---

> ⚠️ **TICK 回测必须选 `local`**，远程服务器不支持 TICK 推送。

---

> 💡 **新手必读**：`examples/` 目录下包含 **25+ 个完整可运行的策略和工具**，从入门到高级全覆盖，**全部已经跑通验证**。强烈推荐先通读以下示例：
>
> - **`B_双均线策略_高性能.py`** — 理解 IndicatorCache v2 高性能写法的最佳入口
> - **`B_海龟交易策略_高性能.py`** — 唐奇安通道 + O(1) 指标查表
> - **`B_多品种多周期交易策略.py`** — 同时交易多个品种、多个周期
> - **`A_工具_导入数据库DB示例.py`** — 本地数据导入必读
> - **`C_纯Tick高频交易策略.py`** — TICK 模式演示
>
> 所有 `*_高性能.py` 示例与普通版**交易逻辑逐字等价**，仅将 Pandas 计算替换为 `register_indicator`，是上手 v0.4.5  fastest 方式。

---

## ⚡ 快速开始

### 1. 安装

**方式一：Git 克隆（推荐，更新最方便）**

```bash
git clone https://github.com/songshuquant/ssquant.git
cd ssquant
pip install -e .
```

**方式二：ZIP 压缩包（无 Git 环境）**

从 GitHub 点击 **Code → Download ZIP** 下载解压，或直接从 Release 下载源码包：

```bash
# 解压后进入目录（目录名可能为 ssquant-main）
cd ssquant-main
pip install -e .
```

**方式三：Gitee 镜像（国内访问更快）**

```bash
git clone https://gitee.com/ssquant/ssquant.git
cd ssquant
pip install -e .
```

> ⚠️ 不再支持 PyPI (`pip install ssquant`)，PyPI 仅保留弃用提示包，真实安装必须通过上述方式。

### 2. 配置账户（首次安装必填）

安装完成后，打开 `ssquant/config/trading_config.py` 填写你的账户信息：

- **俱乐部账号**（`API_USERNAME` / `API_PASSWORD`）：使用**远程数据模式**（`data_server`）时需要。非会员用户可改用**本地数据模式**（`local`），导入本地数据后即可完整回测，功能不受限
- **SIMNOW 账户**：仿真交易时需要，与会员身份无关
- **实盘账户**（`broker_id` / `investor_id` / `password` / `md_server` / `td_server` / `app_id` / `auth_code`）：真实交易时需要，与会员身份无关

> 本地数据模式完全免费，支持回测、TICK、任意周期聚合，功能与远程模式对等（仅数据需自行导入）。如需远程模式可访问 [quant789.com](https://quant789.com) 或关注公众号 **松鼠Quant** 申请俱乐部会员。

### 3. 最小策略

```python
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config

def strategy(api: StrategyAPI):
    close = api.get_close()
    if len(close) < 20:
        return
    ma20 = close.rolling(20).mean().iloc[-1]
    if close.iloc[-1] > ma20 and api.get_pos() <= 0:
        api.buy(volume=1, order_type='next_bar_open')

if __name__ == "__main__":
    config = get_config(RunMode.BACKTEST,
        symbol='rb888', kline_period='1h',
        start_date='2024-01-01', end_date='2025-01-01',
        initial_capital=100000)
    runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
    runner.set_config(config)
    runner.run(strategy=strategy)
```

### 4. 三模式切换（策略代码不改）

```python
# 回测
config = get_config(RunMode.BACKTEST, symbol='rb888',
                    start_date='2024-01-01', end_date='2025-01-01',
                    kline_period='1h')

# SIMNOW 仿真
config = get_config(RunMode.SIMNOW, account='simnow_default',
                    symbol='rb888', kline_period='1m')

# 实盘
config = get_config(RunMode.REAL_TRADING, account='real_default',
                    symbol='rb888', kline_period='1m')
```

---

## 📊 性能实测

| 场景 | v0.4.4 | v0.4.5 | 提升 |
|------|--------|--------|------|
| 单品种双均线 1h/5年 | ~45s | ~1.2s | **37×** |
| 5指标×4数据源 1m/1年 | ~28min | ~18s | **93×** |
| 网格参数优化 400组 | >2h | ~4min | **30×** |

---

## 🎯 关键特性

- **一套代码三处运行** — 回测 / SIMNOW / 实盘，零改动切换
- **高性能 ndarray API** — `get_close_array()` 等零拷贝接口
- **IndicatorCache v2** — 注册一次，O(1) 查询，回测/实盘通用
- **本地数据模式** — SQLite 直读，免会员，支持 TICK
- **多品种多周期** — 同时交易多个品种，独立配置
- **自动移仓** — 主力换月自动平旧开新 (`simultaneous` / `sequential`)
- **智能算法交易** — 限价排队、超时撤单、追价重发
- **订单流数据** — data_server 模式支持 12+ 订单流字段
- **本地复权** — 前复权/后复权，基于合约切换点比例因子
- **AI Agent 技能** — 内置 SKILL.md 标准，支持 Claude/Cursor 等 AI 助手直接编写策略

---

## 🤖 AI 策略助手（ai_agent）

`ai_agent/` 是框架内置的 **AI 驱动策略编写 Web IDE**。你只需用自然语言描述交易思路，AI 自动生成符合 SSQuant 规范的策略代码，并可直接在浏览器内一键回测、查看报告、迭代优化。

### 核心功能

- 💬 **自然语言写策略** — 描述"螺纹钢双均线金叉做多死叉做空"，AI 秒生成完整代码
- 📝 **Monaco 编辑器** — 类 VS Code 的代码编辑体验，支持语法高亮、自动补全
- 🚀 **一键回测** — 生成代码后直接点击运行，实时查看回测结果和 HTML 报告
- 🔄 **自动迭代** — AI 自动分析回测报告，给出优化建议并改写代码
- 📂 **策略管理** — 自动生成策略文件到 `ai_agent/strategies/`，支持多工作区切换

### 启动方式

```bash
cd ai_agent
pip install -r requirements.txt
python app.py
```

打开浏览器访问 **http://localhost:5000**

### 使用流程

1. 点击右上角 ⚙️ **配置 AI 模型 API Key**（支持 OpenAI / 智谱 / 通义千问等兼容 OpenAI 接口的模型）
2. 在对话框输入策略思路，例如：
   > "写一个海龟交易策略，突破20日高点开多，跌破10日低点平仓，用rb888，1小时K线"
3. AI 生成代码 → 自动保存到 `ai_agent/strategies/`
4. 点击 **运行回测**，查看资金曲线、成交记录、绩效指标
5. 点击 **自动优化**，AI 根据回测结果改进参数或逻辑

> 💡 `ai_agent/` 依赖 `ssquant/` 核心框架运行，必须与框架处于同一目录层级。

---

## 📚 文档与示例

| 文档 | 说明 |
|------|------|
| [045.MD](045.MD) | **v0.4.5 更新详情**（性能优化、新接口、迁移指南） |
| [SKILL.md](045/SKILL.md) | 完整框架使用指南（909 行，策略编写 / 回测 / 部署 / 数据） |
| [AGENTS.md](AGENTS.md) | AI Agent 项目上下文 |

**示例策略（`examples/`）**：

强烈建议新手通读 `examples/` 目录下的策略和工具：

- **`B_双均线策略.py`** / **`B_双均线策略_高性能.py`** — 入门首选，对比普通写法与高性能写法
- **`B_海龟交易策略.py`** / **`B_海龟交易策略_高性能.py`** — 唐奇安通道 + IndicatorCache v2
- **`B_多品种多周期交易策略.py`** — 同时交易多个品种、多个周期
- **`A_工具_导入数据库DB示例.py`** — 本地数据导入必读
- **`C_纯Tick高频交易策略.py`** — TICK 模式演示

> 💡 所有 `*_高性能.py` 示例与普通版**交易逻辑完全一致**，仅指标获取方式替换为 `register_indicator`，是理解 v0.4.5 性能优化的最佳入口。

---

## 🗂 项目结构

```
ssquant/
├── ssquant/
│   ├── api/strategy_api.py          # StrategyAPI（新增 ndarray / IndicatorCache 接口）
│   ├── backtest/backtest_core.py    # 回测引擎（性能优化核心）
│   ├── backtest/unified_runner.py   # 统一运行器（三模式入口）
│   ├── backtest/live_trading_adapter.py  # 实盘/SIMNOW 桥接
│   ├── data/data_source.py          # 数据源（ndarray 缓存 / 本地模式）
│   ├── config/trading_config.py     # 账户与默认配置
│   └── ctp/py39~py314/              # CTP 二进制（Windows/Linux）
├── examples/                        # 25+ 示例策略（含高性能版）
├── ai_agent/                        # AI 策略编写助手
└── data_cache/                      # 本地 SQLite / 数据缓存
```

---

## 🌐 社区与主页

- **主页**：[quant789.com](https://quant789.com) — 松鼠俱乐部官网
- **公众号**：**松鼠Quant** — 量化策略、框架更新、会员服务
- **GitHub**：[github.com/songshuquant/ssquant](https://github.com/songshuquant/ssquant)
- **Gitee**：[gitee.com/ssquant/ssquant](https://gitee.com/ssquant/ssquant)（国内镜像）

---

## 🖥 环境要求

- **Python**: 3.9 ~ 3.14
- **系统**: Windows 10+ / Linux (x86_64)
- **CTP**: >= 6.7.7
- **内存**: 4GB+

---

## ⚠️ 风险提示

本框架仅供学习研究。期货交易风险极高：

- 先在 **SIMNOW** 充分测试（建议 ≥ 1 周）
- 实盘前用小资金验证
- 严格止损，勿用高杠杆

---

## 📄 License

[MIT](LICENSE) — 自由使用、修改和分发。
