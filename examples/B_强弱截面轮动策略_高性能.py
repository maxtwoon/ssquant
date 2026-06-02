"""强弱截面轮动策略 - 高性能版本（IndicatorCache v2）

与同目录下 `B_强弱截面轮动策略.py` 行为完全一致。原版每根 Bar 在所有
数据源上对 `close` 全量做 `.pct_change(lookback_period)` 计算相对强弱；
本版在 initialize 钩子里把每个 ds 的 `rs` 一次性注册到 IndicatorCache，
主循环 O(1) 查每个 ds 的当前 rs 值即可排名。

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

def _make_pct_change_func(periods: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).pct_change(periods=periods).to_numpy()
    return _f

def initialize(api: StrategyAPI):
    api.log("强弱轮动策略初始化（高性能版 / IndicatorCache）...")
    lookback_period = api.get_param('lookback_period', 20)
    api.log(f"参数设置 - 回溯期: {lookback_period}")

    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('rs', _make_pct_change_func(lookback_period),
                               window=lookback_period, index=i)
    api.log(f"已注册 rs (相对强弱 = pct_change) （×{ds_count} 数据源）")

def relative_strength_strategy(api: StrategyAPI):
    """版本 A：纯排名轮动（无动量过滤）— 与原版逐字一致。"""
    if not api.require_data_sources(2):
        return

    lookback_period = api.get_param('lookback_period', 20)
    rebalance_period = api.get_param('rebalance_period', 5)

    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)

    data_sources_count = api.get_data_sources_count()

    all_indices = [api.get_idx(i) for i in range(data_sources_count)]
    if len(set(all_indices)) > 1:
        return

    if not hasattr(api, '_last_exec_bar_idx_rs'):
        api._last_exec_bar_idx_rs = -1
    if bar_idx == api._last_exec_bar_idx_rs:
        return

    if bar_idx % 100 == 0:
        api.log(f"当前Bar索引: {bar_idx}, 日期时间: {bar_datetime}")

    if bar_idx < lookback_period:
        return
    if bar_idx % rebalance_period != 0:
        return

    api._last_exec_bar_idx_rs = bar_idx

    # === O(1) 查每个 ds 的当前 rs 值（vs 原版每 ds 全量 pct_change） ===
    current_rs_values = []
    symbol_list = []
    prices = []
    for i in range(data_sources_count):
        rs_now = api.get_indicator('rs', index=i)
        current_rs_values.append(rs_now if not pd.isna(rs_now) else -np.inf)

        ds = api.get_data_source(i)
        symbol_list.append(f"{ds.symbol}_{ds.kline_period}")
        prices.append(api.get_current_price(i) if api.get_current_price(i) is not None else float('nan'))

    ranked_indices = np.argsort(current_rs_values)[::-1]
    strongest_idx = ranked_indices[0]
    weakest_idx = ranked_indices[-1]

    api.log(f"品种相对强弱排名:")
    for rank, idx in enumerate(ranked_indices):
        api.log(f"第{rank + 1}名: {symbol_list[idx]}, 价格: {prices[idx]:.2f}, "
                f"强弱值: {current_rs_values[idx]:.4f}")

    positions = [api.get_pos(i) for i in range(data_sources_count)]
    unit = 1
    target_positions = [0] * data_sources_count
    target_positions[strongest_idx] = unit
    api.log(f"目标: 做多最强品种 {symbol_list[strongest_idx]}")
    target_positions[weakest_idx] = -unit
    api.log(f"目标: 做空最弱品种 {symbol_list[weakest_idx]}")

    for i in range(data_sources_count):
        current_pos = positions[i]
        target_pos = target_positions[i]

        if current_pos == target_pos:
            api.log(f"{symbol_list[i]}: 持仓已符合目标({target_pos})，无需调整")
            continue

        if current_pos != 0:
            api.log(f"平仓 {symbol_list[i]}: {current_pos} → 0")
            api.close_all(order_type='next_bar_open', index=i)

        if target_pos > 0:
            api.log(f"开多 {symbol_list[i]}: 0 → {target_pos}")
            api.buy(volume=target_pos, order_type='next_bar_open', index=i)
        elif target_pos < 0:
            api.log(f"开空 {symbol_list[i]}: 0 → {target_pos}")
            api.sellshort(volume=abs(target_pos), order_type='next_bar_open', index=i)

def relative_strength_momentum_strategy(api: StrategyAPI):
    """版本 B：相对强弱 + 动量过滤（默认入口，与原版逐字一致）。"""
    if not api.require_data_sources(2):
        return

    lookback_period = api.get_param('lookback_period', 20)
    rebalance_period = api.get_param('rebalance_period', 5)

    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)
    if bar_idx % 1 == 0:
        api.log(f"当前Bar索引: {bar_idx}, 日期时间: {bar_datetime}")

    data_sources_count = api.get_data_sources_count()

    all_indices = [api.get_idx(i) for i in range(data_sources_count)]
    if len(set(all_indices)) > 1:
        return

    if not hasattr(api, '_last_exec_bar_idx'):
        api._last_exec_bar_idx = -1
    if bar_idx == api._last_exec_bar_idx:
        return

    if bar_idx < lookback_period:
        return
    if bar_idx % rebalance_period != 0:
        return

    api._last_exec_bar_idx = bar_idx

    # === O(1) 拿每个 ds 当前 rs 值 ===
    current_rs_values = []
    momentum_list = []
    symbol_list = []
    prices = []
    for i in range(data_sources_count):
        rs_now = api.get_indicator('rs', index=i)
        current_rs_values.append(rs_now if not pd.isna(rs_now) else -np.inf)
        # 原版动量与 rs 同源（pct_change(lookback_period)），直接复用
        momentum_list.append(rs_now)

        ds = api.get_data_source(i)
        symbol_list.append(f"{ds.symbol}_{ds.kline_period}")
        prices.append(api.get_current_price(i) if api.get_current_price(i) is not None else float('nan'))

    ranked_indices = np.argsort(current_rs_values)[::-1]
    strongest_idx = ranked_indices[0]
    weakest_idx = ranked_indices[-1]

    strongest_momentum = momentum_list[strongest_idx]
    weakest_momentum = momentum_list[weakest_idx]

    api.log(f"品种相对强弱排名和动量:")
    for rank, idx in enumerate(ranked_indices):
        api.log(f"第{rank + 1}名: {symbol_list[idx]}, 价格: {prices[idx]:.2f}, "
                f"强弱值: {current_rs_values[idx]:.4f}, 动量: {momentum_list[idx]:.4f}")

    positions = [api.get_pos(i) for i in range(data_sources_count)]
    unit = 1
    target_positions = [0] * data_sources_count

    if strongest_momentum > 0:
        target_positions[strongest_idx] = unit
        api.log(f"目标: 做多最强品种 {symbol_list[strongest_idx]}，动量 {strongest_momentum:.4f}")
    else:
        api.log(f"最强品种 {symbol_list[strongest_idx]} 动量为负 {strongest_momentum:.4f}，不做多")

    if weakest_momentum < 0:
        target_positions[weakest_idx] = -unit
        api.log(f"目标: 做空最弱品种 {symbol_list[weakest_idx]}，动量 {weakest_momentum:.4f}")
    else:
        api.log(f"最弱品种 {symbol_list[weakest_idx]} 动量为正 {weakest_momentum:.4f}，不做空")

    for i in range(data_sources_count):
        current_pos = positions[i]
        target_pos = target_positions[i]

        if current_pos == target_pos:
            continue

        if current_pos != 0:
            api.log(f"平仓 {symbol_list[i]}: {current_pos} → 0")
            api.close_all(order_type='next_bar_open', index=i)

        if target_pos > 0:
            api.log(f"开多 {symbol_list[i]}: 0 → {target_pos}")
            api.buy(volume=target_pos, order_type='next_bar_open', index=i)
        elif target_pos < 0:
            api.log(f"开空 {symbol_list[i]}: 0 → {target_pos}")
            api.sellshort(volume=abs(target_pos), order_type='next_bar_open', index=i)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'momentum_period': 20,
        'rebalance_period': 5,
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            start_date='2022-12-01',           # 回测开始日期
            end_date='2026-02-31',             # 回测结束日期
            initial_capital=1000000,           # 初始资金（元）
            align_data=True,                   # 是否对齐多数据源时间轴
            fill_method='ffill',               # 缺失值填充方式: 'ffill'(向前填充)
            lookback_bars=500,                 # 回溯K线窗口（IndicatorCache预热用）
            data_sources=[                     # 多数据源配置（截面轮动需要多个品种）
                {'symbol': 'rb888',             # 合约代码
                 'kline_period': '1m',          # K线周期
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'slippage_ticks': 1,           # 滑点跳数
                 'capital_ratio': 4},           # 资金分配比例
                {'symbol': 'hc888',             # 合约代码
                 'kline_period': '1m',          # K线周期
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'slippage_ticks': 1,           # 滑点跳数
                 'capital_ratio': 4},           # 资金分配比例
                {'symbol': 'i888',              # 合约代码
                 'kline_period': '1m',          # K线周期
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'slippage_ticks': 1,           # 滑点跳数
                 'capital_ratio': 2},           # 资金分配比例
                {'symbol': 'j888',              # 合约代码
                 'kline_period': '1m',          # K线周期
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'slippage_ticks': 1,           # 滑点跳数
                 'capital_ratio': 2},           # 资金分配比例
            ],
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',          # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',               # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            kline_source='data_server',        # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[                     # 多数据源配置
                {'symbol': 'rb888',             # 合约代码
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 5,       # 委托超价跳数
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'auto_roll_enabled': False,    # 是否启用自动移仓（主力换月）
                 'auto_roll_reopen': True,      # 移仓后是否在新主力补回仓位
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
                {'symbol': 'hc888',             # 合约代码
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 5,       # 委托超价跳数
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'auto_roll_enabled': False,    # 是否启用自动移仓
                 'auto_roll_reopen': True,      # 移仓后是否在新主力补回仓位
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
                {'symbol': 'i888',              # 合约代码
                 'kline_period': '2m',          # K线周期
                 'order_offset_ticks': 10,      # 委托超价跳数
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'auto_roll_enabled': False,    # 是否启用自动移仓
                 'auto_roll_reopen': True,      # 移仓后是否在新主力补回仓位
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
                {'symbol': 'j888',              # 合约代码
                 'kline_period': '3m',          # K线周期
                 'order_offset_ticks': 10,      # 委托超价跳数
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'auto_roll_enabled': False,    # 是否启用自动移仓
                 'auto_roll_reopen': True,      # 移仓后是否在新主力补回仓位
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
            ],
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
                {'symbol': 'rb888',             # 合约代码
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 5,       # 委托偏移: 负值=价内挂单，正值=超价
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'auto_roll_enabled': False,    # 是否启用自动移仓（主力换月）
                 'auto_roll_reopen': True,      # 移仓后是否在新主力补回仓位
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
                {'symbol': 'hc888',             # 合约代码
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 5,       # 委托偏移
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'auto_roll_enabled': False,    # 是否启用自动移仓
                 'auto_roll_reopen': True,      # 移仓后是否在新主力补回仓位
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
                {'symbol': 'i888',              # 合约代码
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 10,      # 委托偏移
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'auto_roll_enabled': False,    # 是否启用自动移仓
                 'auto_roll_reopen': True,      # 移仓后是否在新主力补回仓位
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
                {'symbol': 'j888',              # 合约代码
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 10,      # 委托偏移
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'auto_roll_enabled': False,    # 是否启用自动移仓
                 'auto_roll_reopen': True,      # 移仓后是否在新主力补回仓位
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 100,  # 预加载历史K线数量
                 'adjust_type': '1'},           # 复权: '0'不复权, '1'后复权, '2'前复权
            ],
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
    print("强弱截面轮动策略 - 高性能版本（IndicatorCache v2）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    if 'data_sources' in config:
        symbols = [ds['symbol'] for ds in config['data_sources']]
        print(f"交易品种: {', '.join(symbols)}")
    else:
        print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 动量周期={strategy_params['momentum_period']}, 调仓周期={strategy_params['rebalance_period']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=relative_strength_momentum_strategy,
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
