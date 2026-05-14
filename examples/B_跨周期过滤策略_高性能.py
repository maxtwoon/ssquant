"""跨周期过滤策略 - 高性能版本（IndicatorCache v2）

与同目录下 `B_跨周期过滤策略.py` 行为完全一致。原版每根 Bar 在两个数据源
上分别全量重算 MA{long} / MA{short}（共 4 条均线）；本版在 initialize
钩子里按 ds index 分别注册，主循环全部 O(1) 查表。

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低，本文件采用方式一）
═══════════════════════════════════════════════════════════════════
  方式一 — IndicatorCache 注册式（推荐）：与内置指标同速，O(1) 查表
  方式二 — NumPy 数组手动计算：比 Pandas 快 10-30×
  方式三 — Pandas 兼容（老写法）：慢但向后兼容

v2 起 IndicatorCache 在 BACKTEST / SIMNOW / REAL_TRADING 三种模式下统一可用，
且天然支持多数据源（按 index 隔离每个 ds 自己的指标缓存）。
═══════════════════════════════════════════════════════════════════
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np

def _make_sma_func(period: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).rolling(window=period).mean().to_numpy()
    return _f

def initialize(api: StrategyAPI):
    api.log("=" * 80)
    api.log("跨周期过滤策略初始化（高性能版 / IndicatorCache）")
    api.log("=" * 80)

    long_period = api.get_param('long_period', 20)
    short_period = api.get_param('short_period', 5)

    api.log(f"参数设置 - 长周期MA: {long_period}, 短周期MA: {short_period}")
    api.log("策略逻辑：60 分钟趋势过滤 + 15 分钟金叉/死叉入场")

    ds_count = api.get_data_sources_count()
    if ds_count < 2:
        api.log(f"警告：跨周期过滤策略需要 2 个数据源，当前只有 {ds_count} 个")
        return

    # 两个 ds 都注册同样的指标（按 index 隔离，互不干扰）
    for i in range(ds_count):
        api.register_indicator('ma_short', _make_sma_func(short_period),
                               window=short_period, index=i)
        api.register_indicator('ma_long', _make_sma_func(long_period),
                               window=long_period, index=i)
    api.log(f"已注册 ma_short / ma_long （×{ds_count} 数据源）")

def cross_period_strategy(api: StrategyAPI):
    if not api.require_data_sources(2):
        print("没有足够的数据源")
        return

    long_period = api.get_param('long_period', 20)

    bar_idx_15m = api.get_idx(0)
    if bar_idx_15m + 1 < long_period + 5:
        return

    # 也要保证 60m 那侧有足够数据
    if api.get_idx(1) + 1 < long_period + 5:
        return

    # === 短周期(ds 0)：取最近 2 个值用于判断金叉/死叉 ===
    short_arr_0 = api.get_indicator_array('ma_short', window=2, index=0)
    long_arr_0 = api.get_indicator_array('ma_long', window=2, index=0)
    if pd.isna(long_arr_0[-1]):
        return

    curr_short_15m = short_arr_0[-1]
    prev_short_15m = short_arr_0[-2]
    curr_long_15m = long_arr_0[-1]
    prev_long_15m = long_arr_0[-2]

    # === 长周期(ds 1)：只需要当前值用于趋势判断 ===
    curr_short_60m = api.get_indicator('ma_short', index=1)
    curr_long_60m = api.get_indicator('ma_long', index=1)
    if pd.isna(curr_long_60m):
        return

    current_pos = api.get_pos(0)
    current_price = api.get_current_price(0)
    if current_price is None:
        return

    trend_60m_bullish = curr_short_60m > curr_long_60m
    trend_60m_bearish = curr_short_60m < curr_long_60m

    signal_15m_buy = prev_short_15m <= prev_long_15m and curr_short_15m > curr_long_15m
    signal_15m_sell = prev_short_15m >= prev_long_15m and curr_short_15m < curr_long_15m

    # 多头：60m 多头趋势 + 15m 金叉
    if trend_60m_bullish and signal_15m_buy:
        if current_pos <= 0:
            if current_pos < 0:
                api.close_all(order_type='next_bar_open', index=0)
            api.buy(volume=1, order_type='next_bar_open', index=0)

    # 空头：60m 空头趋势 + 15m 死叉
    elif trend_60m_bearish and signal_15m_sell:
        if current_pos >= 0:
            if current_pos > 0:
                api.close_all(order_type='next_bar_open', index=0)
            api.sellshort(volume=1, order_type='next_bar_open', index=0)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'long_period': 20,
        'short_period': 5,
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            start_date='2025-12-01',           # 回测开始日期
            end_date='2026-2-30',              # 回测结束日期
            initial_capital=100000,            # 初始资金（元）
            debug=False,                       # 是否开启调试模式
            align_data=True,                   # 是否对齐多数据源时间轴
            fill_method='ffill',               # 缺失值填充方式: 'ffill'(向前填充)
            lookback_bars=500,                 # 回溯K线窗口（IndicatorCache预热用）
            data_sources=[                     # 多数据源配置（跨周期过滤需要多个周期）
                {'symbol': 'cu888',             # 合约代码
                 'kline_period': '2m',          # K线周期
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'slippage_ticks': 1},          # 滑点跳数
                {'symbol': 'cu888',             # 合约代码
                 'kline_period': '6m',          # K线周期
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'slippage_ticks': 1},          # 滑点跳数
            ],
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',          # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',               # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            kline_source='data_server',        # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[                     # 多数据源配置
                {'symbol': 'cu888',             # 合约代码
                 'kline_period': '2m',          # K线周期
                 'order_offset_ticks': 10,      # 委托超价跳数
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 150,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
                {'symbol': 'cu888',             # 合约代码
                 'kline_period': '6m',          # K线周期
                 'order_offset_ticks': 10,      # 委托超价跳数
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
            ],
            auto_roll_enabled=False,           # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,             # 移仓后是否在新主力补回仓位
            lookback_bars=500,                 # 回溯窗口（IndicatorCache重算范围）
            enable_tick_callback=False,        # 是否启用逐Tick回调（高CPU占用）
            save_kline_csv=False,              # 是否保存K线到CSV文件
            save_kline_db=False,               # 是否保存K线到SQLite数据库
            save_tick_csv=False,               # 是否保存Tick到CSV文件
            save_tick_db=False,                # 是否保存Tick到SQLite数据库
        )
    elif RUN_MODE == RunMode.REAL_TRADING:
        config = get_config(RUN_MODE,
            account='real_default',            # 实盘账户名（必须在 trading_config.py 的 ACCOUNTS 中填写完整信息）
            kline_source='data_server',        # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[                     # 多数据源配置
                {'symbol': 'cu888',             # 合约代码
                 'kline_period': '2m',          # K线周期
                 'order_offset_ticks': 10,      # 委托偏移: 负值=价内挂单，正值=超价
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 150,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
                {'symbol': 'cu888',             # 合约代码
                 'kline_period': '6m',          # K线周期
                 'order_offset_ticks': 10,      # 委托偏移
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
            ],
            auto_roll_enabled=False,           # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,             # 移仓后是否在新主力补回仓位
            lookback_bars=500,                 # 回溯窗口（IndicatorCache重算范围）
            enable_tick_callback=False,        # 是否启用逐Tick回调（高CPU占用）
            save_kline_csv=False,              # 是否保存K线到CSV文件
            save_kline_db=False,               # 是否保存K线到SQLite数据库
            save_tick_csv=False,               # 是否保存Tick到CSV文件
            save_tick_db=False,                # 是否保存Tick到SQLite数据库
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    print("\n" + "=" * 80)
    print("跨周期过滤策略 - 高性能版本（IndicatorCache v2）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    if 'data_sources' in config:
        data_sources_info = [f"{ds['symbol']}_{ds['kline_period']}" for ds in config['data_sources']]
        print(f"数据源: {', '.join(data_sources_info)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 长周期={strategy_params['long_period']}, 短周期={strategy_params['short_period']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=cross_period_strategy,
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
