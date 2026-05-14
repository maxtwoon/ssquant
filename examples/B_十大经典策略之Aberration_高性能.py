"""Aberration策略 - 高性能版本（IndicatorCache v2）

与同目录下 `B_十大经典策略之Aberration.py` 行为完全一致，仅把每根 Bar 全量
重算的布林带/ATR 改为 `initialize` 钩子里 `register_indicator` 一次预计算。

  原版：每根 Bar 调 `close.rolling(N).mean()` / `close.rolling(N).std()` /
        全量 ATR rolling
  本版：initialize 注册 ma / std / atr 三个核心指标，主循环 O(1) 查表，
        上/下轨用 `ma ± k*std` 现算（一次乘加）

═══════════════════════════════════════════════════════════════════
SSQuant 三档性能体系（按性能从高到低，本文件采用方式一）
═══════════════════════════════════════════════════════════════════
  方式一 — IndicatorCache 注册式（推荐）：与内置指标同速，O(1) 查表
  方式二 — NumPy 数组手动计算：比 Pandas 快 10-30×
  方式三 — Pandas 兼容（老写法）：慢但向后兼容

v2 起 IndicatorCache 在 BACKTEST / SIMNOW / REAL_TRADING 三种模式下统一可用。
═══════════════════════════════════════════════════════════════════
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd
import numpy as np

# ====== 指标计算函数（独立可测，签名遵守 register_indicator 协议） ======
def _make_sma_func(period: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).rolling(window=period).mean().to_numpy()
    return _f

def _make_std_func(period: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).rolling(window=period).std().to_numpy()
    return _f

def _make_atr_func(period: int):
    """与原版 strategy_function 中的 ATR 公式完全一致。"""
    def _f(close, open_, high, low, volume):
        hs = pd.Series(high)
        ls = pd.Series(low)
        cs = pd.Series(close)
        tr = pd.DataFrame({
            'hl': hs - ls,
            'hc': (hs - cs.shift(1)).abs(),
            'lc': (ls - cs.shift(1)).abs(),
        }).max(axis=1)
        return tr.rolling(window=period).mean().to_numpy()
    return _f

def initialize(api: StrategyAPI):
    api.log("Aberration策略初始化（高性能版 / IndicatorCache）")
    bb_period = api.get_param('bb_period', 20)
    bb_std = api.get_param('bb_std', 2)
    atr_period = api.get_param('atr_period', 14)
    atr_multiplier = api.get_param('atr_multiplier', 2)

    api.log(f"布林带周期: {bb_period}")
    api.log(f"布林带标准差倍数: {bb_std}")
    api.log(f"ATR周期: {atr_period}")
    api.log(f"ATR倍数止损: {atr_multiplier}")

    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('ma', _make_sma_func(bb_period), window=bb_period, index=i)
        api.register_indicator('std', _make_std_func(bb_period), window=bb_period, index=i)
        api.register_indicator('atr', _make_atr_func(atr_period), window=atr_period, index=i)
    api.log(f"已注册指标: ma / std / atr （×{ds_count} 数据源）")

def strategy_function(api: StrategyAPI):
    bb_period = api.get_param('bb_period', 20)
    bb_std = api.get_param('bb_std', 2)
    atr_period = api.get_param('atr_period', 14)
    atr_multiplier = api.get_param('atr_multiplier', 2)
    current_idx = api.get_idx()

    if current_idx < max(bb_period, atr_period):
        return

    # === O(1) 查表（vs 原版每 Bar 全量 rolling） ===
    ma_val = api.get_indicator('ma')
    std_val = api.get_indicator('std')
    atr_val = api.get_indicator('atr')

    if pd.isna(ma_val) or pd.isna(std_val) or pd.isna(atr_val):
        return

    # 上/下轨现算（一次乘加，无需缓存）
    upper_band = ma_val + bb_std * std_val
    lower_band = ma_val - bb_std * std_val

    current_price = api.get_current_price()
    if current_price is None:
        api.log("警告: 当前价为空")
        return

    current_pos = api.get_pos()

    # 交易逻辑（与原版逐字一致）
    if current_price > upper_band:
        if current_pos <= 0:
            api.close_all(order_type='next_bar_open')
            api.buy(volume=1, order_type='next_bar_open')
            api.log(f"做多信号触发，价格{current_price:.2f}突破上轨{upper_band:.2f}")
            stop_loss_price = current_price - atr_val * atr_multiplier
            api.log(f"设置止损价: {stop_loss_price:.2f}")

    elif current_price < lower_band:
        if current_pos >= 0:
            api.close_all(order_type='next_bar_open')
            api.sellshort(volume=1, order_type='next_bar_open')
            api.log(f"做空信号触发，价格{current_price:.2f}跌破下轨{lower_band:.2f}")
            stop_loss_price = current_price + atr_val * atr_multiplier
            api.log(f"设置止损价: {stop_loss_price:.2f}")

    elif (current_pos > 0 and current_price < ma_val) or \
         (current_pos < 0 and current_price > ma_val):
        api.close_all(order_type='next_bar_open')
        api.log(f"平仓信号触发，价格{current_price:.2f}回归中轨{ma_val:.2f}")

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'bb_period': 20,
        'bb_std': 2,
        'atr_period': 14,
        'atr_multiplier': 2,
    }

    if RUN_MODE == RunMode.BACKTEST:
        config = get_config(RUN_MODE,
            symbol='au888',                    # 合约代码（支持 au2602, au888 等）
            start_date='2025-12-01',           # 回测开始日期
            end_date='2026-01-31',             # 回测结束日期
            kline_period='1m',                 # K线周期: 1m/5m/15m/30m/1h/1d
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            slippage_ticks=1,                  # 滑点跳数（每跳=price_tick）
            initial_capital=100000,            # 初始资金（元）
            lookback_bars=500,                 # 回溯K线窗口（IndicatorCache预热用）
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
        )
    elif RUN_MODE == RunMode.SIMNOW:
        config = get_config(RUN_MODE,
            account='simnow_default',          # 账户名（必须在 trading_config.py 的 ACCOUNTS 中定义）
            server_name='电信1',               # SIMNOW 服务器: 电信1/电信2/移动/TEST/24hour
            kline_source='local',              # K线源: 'local'(CTP本地聚合) 或 'data_server'(远程推送,需账号)
            symbol='au888',                    # 合约代码（888=主力连续，CTP会自动解析为实际合约）
            kline_period='1m',                 # K线周期（CTP Tick合成）
            order_offset_ticks=10,             # 委托超价跳数（+10=对手价+10跳，确保成交）
            algo_trading=False,                # 是否启用智能算法交易（超时重试/撤单重发）
            order_timeout=10,                  # 订单超时时间（秒），0=不启用
            retry_limit=3,                     # 订单失败最大重试次数
            retry_offset_ticks=5,              # 重试时额外超价跳数
            auto_roll_enabled=False,           # 是否启用自动移仓（主力换月）
            auto_roll_reopen=True,             # 移仓后是否在新主力补回仓位
            preload_history=True,              # 是否预加载历史K线（策略初始化前填充）
            history_lookback_bars=100,         # 预加载历史K线数量
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            lookback_bars=500,                 # 回溯窗口（实盘IndicatorCache重算范围）
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
            symbol='au888',                    # 合约代码
            kline_period='1m',                 # K线周期
            order_offset_ticks=10,             # 委托偏移: 负值=价内挂单（低滑点），正值=超价（高成交率）
            algo_trading=False,                # 智能算法交易
            order_timeout=10,                  # 订单超时（秒）
            retry_limit=3,                     # 最大重试次数
            retry_offset_ticks=5,              # 重试超价跳数
            auto_roll_enabled=False,           # 自动移仓
            auto_roll_reopen=True,             # 移仓补回仓位
            preload_history=True,              # 预加载历史K线
            history_lookback_bars=100,         # 预加载K线数
            adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
            lookback_bars=500,                 # 回溯窗口（IndicatorCache重算范围）
            enable_tick_callback=False,        # Tick回调
            save_kline_csv=False,              # 保存K线CSV
            save_kline_db=False,               # 保存K线DB
            save_tick_csv=False,               # 保存Tick CSV
            save_tick_db=False,                # 保存Tick DB
        )
    else:
        raise ValueError(f"不支持的运行模式: {RUN_MODE}")

    print("\n" + "=" * 80)
    print("Aberration策略 - 高性能版本（IndicatorCache v2）")
    print("=" * 80)
    print(f"运行模式: {RUN_MODE.value}")
    print(f"合约代码: {config['symbol']}")
    print(f"策略参数: 布林带周期={strategy_params['bb_period']}, ATR周期={strategy_params['atr_period']}")
    print("=" * 80 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=strategy_function,
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
