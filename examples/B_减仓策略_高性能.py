"""减仓验证策略 - 高性能版本（IndicatorCache v2）

与同目录下 `B_减仓策略.py` 行为完全一致。原版每根 Bar 重算 MA5 / MA20 / RSI；
本版在 initialize 钩子里把 ma_fast / ma_slow / rsi 三个指标一次性注册到
IndicatorCache，主循环 O(1) 查表。

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

_state = {'bars_since_last_reduce': 0}

FAST_PERIOD = 5
SLOW_PERIOD = 20

def _make_sma_func(period: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).rolling(window=period).mean().to_numpy()
    return _f

def _make_rsi_func(period: int):
    """与原版 _rsi(close, period) 完全一致的实现。"""
    def _f(close, open_, high, low, volume):
        cs = pd.Series(close)
        delta = cs.diff()
        gain = delta.clip(lower=0.0)
        loss = (-delta).clip(lower=0.0)
        avg_gain = gain.rolling(period).mean()
        avg_loss = loss.rolling(period).mean()
        rs = avg_gain / avg_loss.replace(0, pd.NA)
        out = 100.0 - (100.0 / (1.0 + rs))
        return pd.to_numeric(out, errors='coerce').to_numpy()
    return _f

def initialize(api: StrategyAPI):
    api.log("=" * 60)
    api.log("减仓验证策略 初始化（高性能版 / IndicatorCache）")
    api.log(f"  开仓手数: {api.get_param('initial_lots', 3)}（一次性开满）")
    api.log(f"  保留底仓: {api.get_param('min_lots', 1)} 手（低于此仅允许全部平仓）")
    api.log(f"  减仓间隔: {api.get_param('reduce_interval', 5)} 根K线")
    api.log(f"  RSI 超买/超卖: {api.get_param('rsi_overbought', 70)} / {api.get_param('rsi_oversold', 30)}")
    api.log("=" * 60)

    rsi_period = api.get_param('rsi_period', 14)

    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('ma_fast', _make_sma_func(FAST_PERIOD), window=FAST_PERIOD, index=i)
        api.register_indicator('ma_slow', _make_sma_func(SLOW_PERIOD), window=SLOW_PERIOD, index=i)
        api.register_indicator('rsi', _make_rsi_func(rsi_period), window=rsi_period, index=i)

def scale_out_strategy(api: StrategyAPI):
    rsi_period = api.get_param('rsi_period', 14)
    need = max(25, rsi_period + 5)
    if api.get_idx(0) < need - 1:
        return

    fast_arr = api.get_indicator_array('ma_fast', window=2, index=0)
    slow_arr = api.get_indicator_array('ma_slow', window=2, index=0)
    rsi_now = api.get_indicator('rsi', index=0)

    if pd.isna(fast_arr[-1]) or pd.isna(slow_arr[-1]) or pd.isna(rsi_now):
        return

    curr_fast = fast_arr[-1]
    prev_fast = fast_arr[-2]
    curr_slow = slow_arr[-1]
    prev_slow = slow_arr[-2]
    curr_rsi = float(rsi_now)

    pos = api.get_pos(0)
    initial_lots = api.get_param('initial_lots', 3)
    min_lots = api.get_param('min_lots', 1)
    reduce_interval = api.get_param('reduce_interval', 5)
    rsi_overbought = api.get_param('rsi_overbought', 70)
    rsi_oversold = api.get_param('rsi_oversold', 30)
    price = api.get_current_price(0)
    if price is None:
        return

    golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
    death_cross = prev_fast >= prev_slow and curr_fast < curr_slow

    if pos == 0:
        _state['bars_since_last_reduce'] = 0
        if golden_cross:
            api.log(f"[金叉] 价格 {price:.2f} → 开多 {initial_lots} 手")
            api.buy(volume=initial_lots, order_type='next_bar_open', index=0)
        elif death_cross:
            api.log(f"[死叉] 价格 {price:.2f} → 开空 {initial_lots} 手")
            api.sellshort(volume=initial_lots, order_type='next_bar_open', index=0)

    elif pos > 0:
        if death_cross:
            api.log(f"[死叉] 价格 {price:.2f} → 平多 {pos} 手")
            api.sell(order_type='next_bar_open', index=0)
            _state['bars_since_last_reduce'] = 0
            return

        _state['bars_since_last_reduce'] += 1
        if (
            pos > min_lots
            and curr_rsi >= rsi_overbought
            and _state['bars_since_last_reduce'] >= reduce_interval
        ):
            api.log(f"[减多] RSI={curr_rsi:.1f} 价格 {price:.2f} → 平多 1 手 (剩余将 {pos - 1})")
            api.sell(volume=1, order_type='next_bar_open', index=0)
            _state['bars_since_last_reduce'] = 0

    elif pos < 0:
        if golden_cross:
            api.log(f"[金叉] 价格 {price:.2f} → 平空 {abs(pos)} 手")
            api.buycover(order_type='next_bar_open', index=0)
            _state['bars_since_last_reduce'] = 0
            return

        _state['bars_since_last_reduce'] += 1
        apos = abs(pos)
        if (
            apos > min_lots
            and curr_rsi <= rsi_oversold
            and _state['bars_since_last_reduce'] >= reduce_interval
        ):
            api.log(f"[减空] RSI={curr_rsi:.1f} 价格 {price:.2f} → 平空 1 手 (剩余将 {apos - 1})")
            api.buycover(volume=1, order_type='next_bar_open', index=0)
            _state['bars_since_last_reduce'] = 0

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'initial_lots': 3,
        'min_lots': 1,
        'reduce_interval': 5,
        'rsi_period': 14,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
    }

    config = get_config(
        RUN_MODE,
        symbol='rb888',                    # 合约代码（支持 au2602, au888 等）
        start_date='2025-01-01',           # 回测开始日期
        end_date='2026-03-30',             # 回测结束日期
        kline_period='15m',                # K线周期: 1m/5m/15m/30m/1h/1d
        adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
        slippage_ticks=1,                  # 滑点跳数（每跳=price_tick）
        initial_capital=100000,            # 初始资金（元）
        lookback_bars=500,                 # 回溯K线窗口（IndicatorCache预热用）
        debug=False,                       # 是否开启调试日志
        data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
    )

    print("\n" + "=" * 60)
    print("减仓策略 - 高性能版本（IndicatorCache v2）")
    print("=" * 60)
    print(f"合约: {config['symbol']}, 周期: {config['kline_period']}")
    print(f"开仓: {strategy_params['initial_lots']} 手 | 底仓不低于: {strategy_params['min_lots']} 手")
    print(f"减仓最小间隔: {strategy_params['reduce_interval']} 根K线")
    print("=" * 60 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=scale_out_strategy,
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
