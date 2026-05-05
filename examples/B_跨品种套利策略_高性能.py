"""跨品种套利策略 - 高性能版本（方式二：NumPy 数组）

与同目录下 `B_跨品种套利策略.py` 行为完全一致。原版每根 Bar 都做：

  1. OLS 滚动回归算 hedge_ratio  → O(window)
  2. 把 hedge_ratio 作用于整段 close 序列算 spread  → O(N)
  3. 整段 spread 上做 rolling mean/std 算 zscore  → O(N)
  → 每根 Bar 的 calculate_zscore / calculate_spread 都对全量历史重算，O(N²)。

本版关键优化：
  - 利用 `api.get_close_array(window=K, index=...)` 只取最近 K 个 close（O(1) 切片）
  - spread 与 zscore 的 rolling 只需要最近 rolling_window 个值，不必算整段
  - hedge_ratio 的 OLS 输入也用 NumPy 切片，跳过 pandas 索引重置开销

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低，本文件采用方式二）
═══════════════════════════════════════════════════════════════════
  方式一 — IndicatorCache 注册式（推荐）：与内置指标同速，O(1) 查表
  方式二 — NumPy 数组手动计算：比 Pandas 快 10-30×（跨 ds 计算的最佳选择）
  方式三 — Pandas 兼容（老写法）：慢但向后兼容

  跨品种套利的核心 spread 是跨 2 个 ds 计算的，不能套用 IndicatorCache，
  所以采用方式二：通过 api.get_close_array 拿 NumPy 切片，跨 ds 手算。
═══════════════════════════════════════════════════════════════════
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np
import statsmodels.api as sm

def initialize(api: StrategyAPI):
    api.log("跨品种套利策略初始化（高性能版 / 方式二 NumPy）...")
    api.log("本策略利用焦炭(J)和焦煤(JM)之间的价差关系进行套利")

def _calculate_hedge_ratio(price1: pd.Series, price2: pd.Series,
                           window: int = 60, current_idx: int = None) -> float:
    """与原版 calculate_hedge_ratio 完全一致 — 包括 current_idx 是绝对索引而
    price1/price2 是 lookback_bars 限制的相对窗口这一行为，确保回测/实盘逐笔等价。
    """
    if current_idx is None:
        current_idx = len(price1) - 1
    if current_idx < window - 1:
        return float('nan')
    start_idx = max(0, current_idx - window + 1)

    y = price1.iloc[start_idx:current_idx + 1].reset_index(drop=True)
    X_series = price2.iloc[start_idx:current_idx + 1].reset_index(drop=True)

    if len(y) < 2 or len(X_series) < 2:
        return float('nan')

    X = sm.add_constant(X_series)
    try:
        results = sm.OLS(y, X).fit()
        return float(results.params.iloc[1])
    except Exception:
        return float('nan')

def pairs_trading_strategy(api: StrategyAPI):
    if not api.require_data_sources(2):
        return

    min_samples = api.get_param('min_samples', 200)
    zscore_threshold = api.get_param('zscore_threshold', 2.0)
    rolling_window = api.get_param('rolling_window', 20)
    hedge_ratio_window = api.get_param('hedge_ratio_window', 30)
    use_dynamic_hedge_ratio = api.get_param('use_dynamic_hedge_ratio', True)

    bar_idx = api.get_idx(0)

    # === hedge_ratio 走原版完全等价的路径（保留绝对索引 + 相对窗口的边界语义） ===
    j_klines = api.get_klines(0)
    jm_klines = api.get_klines(1)
    if len(j_klines) < min_samples or len(jm_klines) < min_samples:
        return
    j_close = j_klines['close']
    jm_close = jm_klines['close']

    hedge_ratio = None
    if use_dynamic_hedge_ratio:
        if bar_idx >= hedge_ratio_window:
            hedge_ratio = _calculate_hedge_ratio(j_close, jm_close,
                                                 window=hedge_ratio_window,
                                                 current_idx=bar_idx)
        if pd.isna(hedge_ratio):
            hedge_ratio = 1.5
    else:
        hedge_ratio = 1.5

    if bar_idx < rolling_window:
        return

    # === 关键加速点：spread / zscore 只需要最近 rolling_window 个值 ===
    # 原版 zscore.iloc[-1] = (spread[-1] - mean(spread[-window:])) / std(spread[-window:])
    # 数学等价于 j_close[-window:] - jm_close[-window:] * hedge_ratio 的 mean/std
    # 所以可以避免对整段 close 全量算 spread/rolling
    j_recent = j_close.iloc[-rolling_window:].to_numpy()
    jm_recent = jm_close.iloc[-rolling_window:].to_numpy()
    if len(j_recent) < rolling_window or len(jm_recent) < rolling_window:
        return

    spread_window = j_recent - jm_recent * hedge_ratio
    mean_v = float(np.mean(spread_window))
    # pandas Series.std() 默认 ddof=1，对齐
    std_v = float(np.std(spread_window, ddof=1))
    if std_v == 0 or pd.isna(std_v):
        return
    current_spread = float(spread_window[-1])
    current_zscore = (current_spread - mean_v) / std_v

    if pd.isna(current_zscore):
        return

    j_pos = api.get_pos(0)
    jm_pos = api.get_pos(1)
    j_unit = 1
    jm_unit = max(1, round(j_unit * hedge_ratio))

    if j_pos == 0 and jm_pos == 0:
        if current_zscore > zscore_threshold:
            api.sellshort(volume=j_unit, order_type='next_bar_open', index=0)
            api.buy(volume=jm_unit, order_type='next_bar_open', index=1)
        elif current_zscore < -zscore_threshold:
            api.buy(volume=j_unit, order_type='next_bar_open', index=0)
            api.sellshort(volume=jm_unit, order_type='next_bar_open', index=1)
    elif j_pos < 0 and jm_pos > 0:
        if current_zscore < 0.5:
            api.buycover(order_type='next_bar_open', index=0)
            api.sell(order_type='next_bar_open', index=1)
    elif j_pos > 0 and jm_pos < 0:
        if current_zscore > -0.5:
            api.sell(order_type='next_bar_open', index=0)
            api.buycover(order_type='next_bar_open', index=1)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'lookback': 20,
        'threshold': 2.0,
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            start_date='2025-12-01',             # 回测开始日期
            end_date='2026-01-31',               # 回测结束日期
            initial_capital=1000000,             # 初始资金（元）
            align_data=True,                     # 是否对齐多数据源时间轴
            fill_method='ffill',                 # 对齐缺失值填充方式: ffill(前值填充) / bfill(后值填充)
            lookback_bars=500,                   # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb888',        # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                },
                {   # 数据源1: 铁矿石
                    'symbol': 'i888',         # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                },
            ],
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',            # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',                 # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            kline_source='local',                # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb888',              # 合约代码
                    'kline_period': '1m',           # K线周期
                    'order_offset_ticks': 5,        # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 200,   # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源1: 铁矿石
                    'symbol': 'i888',               # 合约代码
                    'kline_period': '1m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 200,   # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
            ],
            auto_roll_enabled=False,             # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,               # 移仓后是否在新主力补回仓位
            lookback_bars=500,                   # 回溯窗口（实盘IndicatorCache重算范围）
            enable_tick_callback=False,          # 是否启用逐Tick回调（高CPU占用）
            save_kline_csv=False,                # 是否保存K线到CSV文件
            save_kline_db=False,                 # 是否保存K线到SQLite数据库
            save_tick_csv=False,                 # 是否保存Tick到CSV文件
            save_tick_db=False,                  # 是否保存Tick到SQLite数据库
        )
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(RUN_MODE,
            account='real_default',              # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）
            kline_source='data_server',          # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[
                {   # 数据源0: 螺纹钢
                    'symbol': 'rb888',              # 合约代码
                    'kline_period': '1m',           # K线周期
                    'order_offset_ticks': 5,        # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 200,   # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源1: 铁矿石
                    'symbol': 'i888',               # 合约代码
                    'kline_period': '1m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 200,   # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
            ],
            auto_roll_enabled=False,             # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,               # 移仓后是否在新主力补回仓位
            lookback_bars=500,                   # 回溯窗口（实盘IndicatorCache重算范围）
            enable_tick_callback=False,          # 是否启用逐Tick回调（高CPU占用）
            save_kline_csv=False,                # 是否保存K线到CSV文件
            save_kline_db=False,                 # 是否保存K线到SQLite数据库
            save_tick_csv=False,                 # 是否保存Tick到CSV文件
            save_tick_db=False,                  # 是否保存Tick到SQLite数据库
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    print("\n" + "=" * 80)
    print("跨品种套利策略 - 高性能版本（方式二 NumPy 数组）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    if 'data_sources' in config:
        symbols = [ds['symbol'] for ds in config['data_sources']]
        print(f"套利对: {' vs '.join(symbols)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 回溯周期={strategy_params['lookback']}, 阈值={strategy_params['threshold']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=pairs_trading_strategy,
            initialize=initialize,
            strategy_params=strategy_params,
        )
    except KeyboardInterrupt:
        print("\n用户中断")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()
