"""多品种多周期交易策略 - 高性能版本（IndicatorCache v2）

与同目录下 `B_多品种多周期交易策略.py` 行为完全一致。原版每根 Bar 在 4 个
数据源上都全量重算 MA{fast} / MA{slow}（共 8 条均线）；本版在 initialize
钩子里按 ds index 分别注册，主循环全部 O(1) 查表。

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低，本文件采用方式一）
═══════════════════════════════════════════════════════════════════
  方式一 — IndicatorCache 注册式（推荐）：与内置指标同速，O(1) 查表
  方式二 — NumPy 数组手动计算：比 Pandas 快 10-30×
  方式三 — Pandas 兼容（老写法）：慢但向后兼容

v2 起 IndicatorCache 在 BACKTEST / SIMNOW / REAL_TRADING 三种模式下统一可用，
天然支持多数据源（按 index 隔离每个 ds 自己的指标缓存）。
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
    api.log("多数据源策略初始化（高性能版 / IndicatorCache）...")
    api.log("所有交易将使用下一根K线开盘价执行 (order_type='next_bar_open')")

    fast_ma = api.get_param('fast_ma', 5)
    slow_ma = api.get_param('slow_ma', 20)

    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('ma_fast', _make_sma_func(fast_ma), window=fast_ma, index=i)
        api.register_indicator('ma_slow', _make_sma_func(slow_ma), window=slow_ma, index=i)
    api.log(f"已注册 ma_fast / ma_slow （×{ds_count} 数据源）")

def _ma_signals(api: StrategyAPI, ds_index: int):
    """从 IndicatorCache O(1) 拿最近 2 个均线值，返回 (long_signal, short_signal)。"""
    fast_arr = api.get_indicator_array('ma_fast', window=2, index=ds_index)
    slow_arr = api.get_indicator_array('ma_slow', window=2, index=ds_index)
    if fast_arr is None or slow_arr is None:
        return False, False, None, None
    if len(fast_arr) < 2 or len(slow_arr) < 2:
        return False, False, None, None
    if pd.isna(slow_arr[-1]) or pd.isna(fast_arr[-1]) or pd.isna(slow_arr[-2]) or pd.isna(fast_arr[-2]):
        return False, False, None, None

    long_signal = fast_arr[-2] <= slow_arr[-2] and fast_arr[-1] > slow_arr[-1]
    short_signal = fast_arr[-2] >= slow_arr[-2] and fast_arr[-1] < slow_arr[-1]
    return long_signal, short_signal, fast_arr[-1], slow_arr[-1]

def _trade_one_ds(api: StrategyAPI, ds_index: int, name: str, unit: int = 1):
    """每个 ds 独立的交易逻辑（与原版逐字一致）。"""
    long_signal, short_signal, _, _ = _ma_signals(api, ds_index)

    pos = api.get_pos(ds_index)
    price = api.get_current_price(ds_index)
    if price is None:
        return

    if pos > 0:  # 持多
        if short_signal:
            api.log(f"{name} 短期均线下穿长期均线，平多仓，价格：{price:.2f}，将在下一根K线开盘价执行")
            api.sell(volume=unit, order_type='next_bar_open', index=ds_index)
            api.log(f"{name} 短期均线下穿长期均线，开空仓，价格：{price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=ds_index)
    elif pos < 0:  # 持空
        if long_signal:
            api.log(f"{name} 短期均线上穿长期均线，平空仓，价格：{price:.2f}，将在下一根K线开盘价执行")
            api.buycover(volume=unit, order_type='next_bar_open', index=ds_index)
            api.log(f"{name} 短期均线上穿长期均线，开多仓，价格：{price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=ds_index)
    else:  # 空仓
        if long_signal:
            api.log(f"{name} 短期均线上穿长期均线，开多仓，价格：{price:.2f}，将在下一根K线开盘价执行")
            api.buy(volume=unit, order_type='next_bar_open', index=ds_index)
        elif short_signal:
            api.log(f"{name} 短期均线下穿长期均线，开空仓，价格：{price:.2f}，将在下一根K线开盘价执行")
            api.sellshort(volume=unit, order_type='next_bar_open', index=ds_index)

def multi_source_strategy(api: StrategyAPI):
    """多数据源策略 — 4 个 ds 独立交易，每个 ds 走 IndicatorCache 查表。"""
    fast_ma = api.get_param('fast_ma', 5)
    slow_ma = api.get_param('slow_ma', 20)

    if not api.require_data_sources(4):
        return

    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)

    if bar_idx % 1 == 0:
        api.log(f"当前Bar索引: {bar_idx}, 日期时间: {bar_datetime}")
        api.log(f"策略参数 - 快线周期: {fast_ma}, 慢线周期: {slow_ma}")
        for i in range(4):
            ds = api.get_data_source(i)
            if ds:
                api.log(f"数据源{i}: {ds.symbol}_{ds.kline_period}, 当前价格: {ds.current_price}, 持仓: {ds.current_pos}")

    min_data_len = max(fast_ma, slow_ma) + 5
    for i in range(4):
        if api.get_idx(i) + 1 < min_data_len:
            return

    # 4 个 ds 独立交易（顺序与原版一致）
    _trade_one_ds(api, 0, "J888 5分钟K线")
    _trade_one_ds(api, 1, "J888 15分钟K线")
    _trade_one_ds(api, 2, "JM888 5分钟K线")
    _trade_one_ds(api, 3, "JM888 15分钟K线")

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.SIMNOW

    strategy_params = {'fast_ma': 5, 'slow_ma': 20}

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            start_date='2025-12-01',             # 回测开始日期
            end_date='2026-4-31',                # 回测结束日期
            initial_capital=1000000,             # 初始资金（元）
            align_data=False,                    # 是否对齐多数据源时间轴
            fill_method='ffill',                 # 对齐缺失值填充方式: ffill(前值填充) / bfill(后值填充)
            lookback_bars=500,                   # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
            data_sources=[
                {   # 数据源0: 焦炭 1分钟
                    'symbol': 'j888',         # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                    'capital_ratio': 8,       # 资金权重: 8/12
                },
                {   # 数据源1: 焦炭 5分钟
                    'symbol': 'j888',         # 合约代码
                    'kline_period': '5m',     # K线周期
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                    'capital_ratio': 1,       # 资金权重: 1/12
                },
                {   # 数据源2: 焦煤 1分钟
                    'symbol': 'jm888',        # 合约代码
                    'kline_period': '1m',     # K线周期
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                    'capital_ratio': 3,       # 资金权重: 3/12
                },
                {   # 数据源3: 焦煤 5分钟
                    'symbol': 'jm888',        # 合约代码
                    'kline_period': '5m',     # K线周期
                    'adjust_type': '1',       # 复权: '0'不复权, '1'后复权, '2'前复权
                    'slippage_ticks': 1,      # 滑点跳数
                    'capital_ratio': 2,       # 资金权重: 2/12
                },
            ],
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',            # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',                 # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            kline_source='data_server',                # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[
                {   # 数据源0: 焦炭 1分钟
                    'symbol': 'j888',               # 合约代码
                    'kline_period': '1m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'auto_roll_enabled': False,     # 自动移仓
                    'auto_roll_reopen': True,       # 移仓补回仓位
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 2000,  # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源1: 焦炭 5分钟
                    'symbol': 'j888',               # 合约代码
                    'kline_period': '5m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'auto_roll_enabled': False,     # 自动移仓
                    'auto_roll_reopen': True,       # 移仓补回仓位
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 2000,  # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源2: 焦煤 1分钟
                    'symbol': 'jm888',              # 合约代码
                    'kline_period': '1m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'auto_roll_enabled': False,     # 自动移仓
                    'auto_roll_reopen': True,       # 移仓补回仓位
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 2000,  # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源3: 焦煤 5分钟
                    'symbol': 'jm888',              # 合约代码
                    'kline_period': '5m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'auto_roll_enabled': False,     # 自动移仓
                    'auto_roll_reopen': True,       # 移仓补回仓位
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 2000,  # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
            ],
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
            kline_source='local',          # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[
                {   # 数据源0: 焦炭 1分钟
                    'symbol': 'j888',               # 合约代码
                    'kline_period': '1m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'auto_roll_enabled': False,     # 自动移仓
                    'auto_roll_reopen': True,       # 移仓补回仓位
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 2000,  # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源1: 焦炭 5分钟
                    'symbol': 'j888',               # 合约代码
                    'kline_period': '5m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'auto_roll_enabled': False,     # 自动移仓
                    'auto_roll_reopen': True,       # 移仓补回仓位
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 2000,  # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源2: 焦煤 1分钟
                    'symbol': 'jm888',              # 合约代码
                    'kline_period': '1m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'auto_roll_enabled': False,     # 自动移仓
                    'auto_roll_reopen': True,       # 移仓补回仓位
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 2000,  # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
                {   # 数据源3: 焦煤 5分钟
                    'symbol': 'jm888',              # 合约代码
                    'kline_period': '5m',           # K线周期
                    'order_offset_ticks': 10,       # 委托超价跳数
                    'algo_trading': False,          # 智能算法交易
                    'order_timeout': 10,            # 订单超时（秒）
                    'retry_limit': 3,               # 最大重试次数
                    'retry_offset_ticks': 5,        # 重试超价跳数
                    'auto_roll_enabled': False,     # 自动移仓
                    'auto_roll_reopen': True,       # 移仓补回仓位
                    'preload_history': True,        # 预加载历史K线
                    'history_lookback_bars': 2000,  # 预加载K线数
                    'adjust_type': '1',             # 复权: '0'不复权, '1'后复权, '2'前复权
                },
            ],
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
    print("多品种多周期交易策略 - 高性能版本（IndicatorCache v2）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    if 'data_sources' in config:
        data_sources_info = [f"{ds['symbol']}_{ds['kline_period']}" for ds in config['data_sources']]
        print(f"数据源: {', '.join(data_sources_info)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 快线={strategy_params['fast_ma']}, 慢线={strategy_params['slow_ma']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=multi_source_strategy,
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
