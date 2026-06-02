"""混合开平仓示例 - 高性能版本（IndicatorCache v2）

与同目录下 `B_正反手混合开平仓策略.py` 行为完全一致。原版每根 Bar 重算
MA{fast} / MA{slow} / RSI；本版在 initialize 钩子里把这三个指标一次性注册
到 IndicatorCache，主循环 O(1) 查表。

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

def _make_sma_func(period: int):
    def _f(close, open_, high, low, volume):
        return pd.Series(close).rolling(window=period).mean().to_numpy()
    return _f

def _make_rsi_func(period: int):
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
    api.log("混合开平仓策略 初始化（高性能版 / IndicatorCache）")
    fast_n = api.get_param('fast', 5)
    slow_n = api.get_param('slow', 20)
    rsi_period = api.get_param('rsi_period', 14)
    api.log(f"  手数: {api.get_param('volume', 1)}")
    api.log(f"  MA: {fast_n} / {slow_n}")
    api.log(
        f"  RSI({rsi_period}) "
        f"多平≥{api.get_param('rsi_overbought', 72)} "
        f"空平≤{api.get_param('rsi_oversold', 28)}"
    )
    api.log("=" * 60)

    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('ma_fast', _make_sma_func(fast_n), window=fast_n, index=i)
        api.register_indicator('ma_slow', _make_sma_func(slow_n), window=slow_n, index=i)
        api.register_indicator('rsi', _make_rsi_func(rsi_period), window=rsi_period, index=i)

def mixed_open_close_strategy(api: StrategyAPI):
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
    vol = api.get_param('volume', 1)
    ot = api.get_param('order_type', 'next_bar_open')
    ob = api.get_param('rsi_overbought', 72)
    os_level = api.get_param('rsi_oversold', 28)
    price = api.get_current_price(0)
    if price is None:
        return

    golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
    death_cross = prev_fast >= prev_slow and curr_fast < curr_slow

    if pos > 0 and death_cross:
        api.log(f"[反手] 死叉 持多 {pos} 手 @ {price:.2f} → reverse_pos（平多开空）")
        api.reverse_pos(reason="死叉反手", order_type=ot, index=0)
        return
    if pos < 0 and golden_cross:
        api.log(f"[反手] 金叉 持空 {abs(pos)} 手 @ {price:.2f} → reverse_pos（平空开多）")
        api.reverse_pos(reason="金叉反手", order_type=ot, index=0)
        return

    if pos > 0 and not death_cross and curr_rsi >= ob:
        api.log(f"[多平] RSI={curr_rsi:.1f} 持多 {pos} 手 @ {price:.2f} → sell 全平")
        api.sell(order_type=ot, index=0)
        return
    if pos < 0 and not golden_cross and curr_rsi <= os_level:
        api.log(f"[空平] RSI={curr_rsi:.1f} 持空 {abs(pos)} 手 @ {price:.2f} → buycover 全平")
        api.buycover(order_type=ot, index=0)
        return

    if pos == 0 and golden_cross:
        api.log(f"[多开] 金叉 @ {price:.2f} → buy {vol} 手")
        api.buy(volume=vol, order_type=ot, index=0)
    elif pos == 0 and death_cross:
        api.log(f"[空开] 死叉 @ {price:.2f} → sellshort {vol} 手")
        api.sellshort(volume=vol, order_type=ot, index=0)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'volume': 1,                       # 开仓手数
        'fast': 5,                         # 快线周期
        'slow': 20,                        # 慢线周期
        'rsi_period': 14,                  # RSI周期
        'rsi_overbought': 72,              # RSI超买阈值
        'rsi_oversold': 28,                # RSI超卖阈值
        'order_type': 'next_bar_open',     # 下单类型
    }

    config = get_config(
        RUN_MODE,
        symbol='rb888',                    # 合约代码（支持 au888 等）
        start_date='2025-01-01',           # 回测开始日期
        end_date='2026-03-30',             # 回测结束日期
        kline_period='15m',                # K线周期: 1m/5m/15m/30m/1h/1d
        adjust_type='1',                   # 复权: '0'不复权, '1'后复权, '2'前复权
        slippage_ticks=1,                  # 滑点跳数（每跳=price_tick）
        initial_capital=100000,            # 初始资金（元）
        lookback_bars=500,                 # 回溯K线窗口（IndicatorCache预热用）
        debug=False,                       # 是否启用调试模式
        data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
    )

    print("\n" + "=" * 60)
    print("混合开平仓 - 高性能版本（IndicatorCache v2）")
    print("=" * 60)
    print(f"合约: {config['symbol']}, 周期: {config['kline_period']}")
    print("=" * 60 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        runner.run(
            strategy=mixed_open_close_strategy,
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
