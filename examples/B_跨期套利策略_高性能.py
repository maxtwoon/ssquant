"""跨期套利策略 - 高性能版本（方式二：NumPy 数组）

与同目录下 `B_跨期套利策略.py` 行为完全一致。原版每根 Bar 都做：

  1. spread = near_close - far_close  → O(N) 整段计算
  2. zscore = (spread - rolling_mean) / rolling_std  → O(N) 整段计算
  → 实际只用最后一个 zscore 值，导致 O(N²)。

本版关键优化：
  - 用 `iloc[-rolling_window:]` 只取最近 K 个 close（pandas 切片 O(K)）
  - 转 NumPy 后手算 mean/std（避免 rolling 全量计算）
  - 跨 ds 计算的 spread 不能直接走 IndicatorCache，所以采用方式二

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低，本文件采用方式二）
═══════════════════════════════════════════════════════════════════
  方式一 — IndicatorCache 注册式（推荐）：与内置指标同速，O(1) 查表
  方式二 — NumPy 数组手动计算：比 Pandas 快 10-30×（跨 ds 计算的最佳选择）
  方式三 — Pandas 兼容（老写法）：慢但向后兼容
═══════════════════════════════════════════════════════════════════
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np

def initialize(api: StrategyAPI):
    api.log("=" * 60)
    api.log("跨期套利策略初始化（高性能版 / 方式二 NumPy）...")
    api.log("本策略利用同一品种主力合约与次主力合约之间的价差进行套利")
    api.log("=" * 60)

def calendar_spread_strategy(api: StrategyAPI):
    """跨期套利主函数 — trade 决策与原版逐字一致，只是 spread/zscore 走 NumPy。"""
    if not api.require_data_sources(2):
        return

    min_samples = api.get_param('min_samples', 100)
    zscore_threshold = api.get_param('zscore_threshold', 2.0)
    zscore_close = api.get_param('zscore_close', 0.5)
    rolling_window = api.get_param('rolling_window', 20)
    trade_volume = api.get_param('trade_volume', 1)

    bar_idx = api.get_idx(0)
    bar_datetime = api.get_datetime(0)

    # 数据量检查（仅一次 get_klines 取 DataFrame，复用 close）
    near_klines = api.get_klines(0)
    far_klines = api.get_klines(1)
    if len(near_klines) < min_samples or len(far_klines) < min_samples:
        if bar_idx % 100 == 0:
            api.log(f"数据不足: 近月{len(near_klines)}条, 远月{len(far_klines)}条, 需要{min_samples}条")
        return

    if bar_idx < rolling_window:
        return

    # === 关键加速点：只取最近 rolling_window 个 close ===
    near_recent = near_klines['close'].iloc[-rolling_window:].to_numpy()
    far_recent = far_klines['close'].iloc[-rolling_window:].to_numpy()
    if len(near_recent) < rolling_window or len(far_recent) < rolling_window:
        return

    spread_window = near_recent - far_recent  # hedge_ratio = 1

    mean_v = float(np.mean(spread_window))
    # 与 pandas Series.std() 默认 ddof=1 保持一致
    std_v = float(np.std(spread_window, ddof=1))
    if std_v == 0 or pd.isna(std_v):
        return
    current_spread = float(spread_window[-1])
    current_zscore = (current_spread - mean_v) / std_v
    if pd.isna(current_zscore):
        return

    near_pos = api.get_pos(0)
    far_pos = api.get_pos(1)
    near_price = api.get_price(0)
    far_price = api.get_price(1)

    if bar_idx % 20 == 0:
        api.log(f"[{bar_datetime}] 价差:{current_spread:.2f} Z分数:{current_zscore:.2f} | "
                f"近月持仓:{near_pos} 远月持仓:{far_pos}")

    # ========== 交易逻辑（与原版逐字一致） ==========
    if near_pos == 0 and far_pos == 0:
        if current_zscore > zscore_threshold:
            api.log(f"开仓做空价差 | Z={current_zscore:.2f} > {zscore_threshold}")
            api.log(f"   卖出近月@{near_price:.2f}, 买入远月@{far_price:.2f}")
            api.sellshort(volume=trade_volume, order_type='next_bar_open', index=0)
            api.buy(volume=trade_volume, order_type='next_bar_open', index=1)
        elif current_zscore < -zscore_threshold:
            api.log(f"开仓做多价差 | Z={current_zscore:.2f} < {-zscore_threshold}")
            api.log(f"   买入近月@{near_price:.2f}, 卖出远月@{far_price:.2f}")
            api.buy(volume=trade_volume, order_type='next_bar_open', index=0)
            api.sellshort(volume=trade_volume, order_type='next_bar_open', index=1)

    elif near_pos < 0 and far_pos > 0:
        if current_zscore < zscore_close:
            api.log(f"平仓做空价差 | Z={current_zscore:.2f} < {zscore_close}")
            api.buycover(order_type='next_bar_open', index=0)
            api.sell(order_type='next_bar_open', index=1)

    elif near_pos > 0 and far_pos < 0:
        if current_zscore > -zscore_close:
            api.log(f"平仓做多价差 | Z={current_zscore:.2f} > {-zscore_close}")
            api.sell(order_type='next_bar_open', index=0)
            api.buycover(order_type='next_bar_open', index=1)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'min_samples': 100,
        'zscore_threshold': 2.0,
        'zscore_close': 0.5,
        'rolling_window': 20,
        'trade_volume': 1,
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            start_date='2025-12-01',           # 回测开始日期
            end_date='2026-01-31',             # 回测结束日期
            initial_capital=100000,            # 初始资金（元）
            align_data=True,                   # 是否对齐多数据源时间轴
            fill_method='ffill',               # 缺失值填充方式: 'ffill'(向前填充)
            lookback_bars=500,                 # 回溯K线窗口（IndicatorCache预热用）
            data_sources=[                     # 多数据源配置（跨期套利需要近月与远月）
                {'symbol': 'rb888',             # 合约代码（近月/主力）
                 'kline_period': '1m',          # K线周期
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'slippage_ticks': 1,           # 滑点跳数
                 'initial_capital': 20000},     # 该数据源分配初始资金（元）
                {'symbol': 'rb777',             # 合约代码（远月/次主力）
                 'kline_period': '1m',          # K线周期
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'slippage_ticks': 1,           # 滑点跳数
                 'initial_capital': 20000},     # 该数据源分配初始资金（元）
            ],
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',          # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',               # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            kline_source='data_server',        # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            data_sources=[                     # 多数据源配置
                {'symbol': 'rb888',             # 合约代码（近月/主力）
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 5,       # 委托超价跳数
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 200,  # 预加载历史K线数量
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'history_symbol': 'rb888'},    # 历史数据合约代码
                {'symbol': 'rb777',             # 合约代码（远月/次主力）
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 5,       # 委托超价跳数
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 200,  # 预加载历史K线数量
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'history_symbol': 'rb777'},    # 历史数据合约代码
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
                {'symbol': 'rb888',             # 合约代码（近月/主力）
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 5,       # 委托偏移: 负值=价内挂单，正值=超价
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 200,  # 预加载历史K线数量
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'history_symbol': 'rb888'},    # 历史数据合约代码
                {'symbol': 'rb777',             # 合约代码（远月/次主力）
                 'kline_period': '1m',          # K线周期
                 'order_offset_ticks': 5,       # 委托偏移
                 'algo_trading': False,         # 是否启用智能算法交易
                 'order_timeout': 10,           # 订单超时时间（秒）
                 'retry_limit': 3,              # 订单失败最大重试次数
                 'retry_offset_ticks': 5,       # 重试时额外超价跳数
                 'preload_history': True,       # 是否预加载历史K线
                 'history_lookback_bars': 200,  # 预加载历史K线数量
                 'adjust_type': '1',            # 复权: '0'不复权, '1'后复权, '2'前复权
                 'history_symbol': 'rb777'},    # 历史数据合约代码
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
    print("跨期套利策略 - 高性能版本（方式二 NumPy 数组）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    if 'data_sources' in config:
        symbols = [ds['symbol'] for ds in config['data_sources']]
        print(f"套利对: {symbols[0]} (近月) vs {symbols[1]} (远月)")
    print(f"策略参数:")
    print(f"  - 开仓阈值: Z > {strategy_params['zscore_threshold']} 或 Z < {-strategy_params['zscore_threshold']}")
    print(f"  - 平仓阈值: |Z| < {strategy_params['zscore_close']}")
    print(f"  - 滚动窗口: {strategy_params['rolling_window']}")
    print(f"  - 交易手数: {strategy_params['trade_volume']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=calendar_spread_strategy,
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
