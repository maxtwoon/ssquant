"""
混合开平仓示例 — 同一策略内同时演示：

  - 多开 / 空开：空仓时，均线金叉开多、死叉开空（普通开仓）
  - 多平 / 空平：持仓时，RSI 极端止盈离场（sell / buycover 全平），不产生反向持仓
  - 正反手：持仓时，均线反向交叉用 reverse_pos（平多开空 / 平空开多）

判定顺序（同一根 K 线内只走一条分支，避免重复下单）：
  1. 持多 + 死叉 → 反手（空）
  2. 持空 + 金叉 → 反手（多）
  3. 持多 + RSI 超买（且本根未触发死叉）→ 多平
  4. 持空 + RSI 超卖（且本根未触发金叉）→ 空平
  5. 空仓 + 金叉 → 开多
  6. 空仓 + 死叉 → 开空

说明：RSI 平仓分支要求「本根未出现同向交叉」，否则已由 1、2 反手处理。
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd

def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    out = 100.0 - (100.0 / (1.0 + rs))
    return pd.to_numeric(out, errors='coerce')

def initialize(api: StrategyAPI):
    api.log("=" * 60)
    api.log("混合开平仓策略 初始化")
    api.log(f"  手数: {api.get_param('volume', 1)}")
    api.log(f"  MA: {api.get_param('fast', 5)} / {api.get_param('slow', 20)}")
    api.log(
        f"  RSI({api.get_param('rsi_period', 14)}) "
        f"多平≥{api.get_param('rsi_overbought', 72)} "
        f"空平≤{api.get_param('rsi_oversold', 28)}"
    )
    api.log("=" * 60)

def mixed_open_close_strategy(api: StrategyAPI):
    rsi_period = api.get_param('rsi_period', 14)
    need = max(25, rsi_period + 5)
    klines = api.get_klines(0)
    if len(klines) < need:
        return

    close = klines['close']
    fast_n = api.get_param('fast', 5)
    slow_n = api.get_param('slow', 20)
    ma_fast = close.rolling(fast_n).mean()
    ma_slow = close.rolling(slow_n).mean()
    rsi = _rsi(close, rsi_period)

    if pd.isna(ma_fast.iloc[-1]) or pd.isna(ma_slow.iloc[-1]) or pd.isna(rsi.iloc[-1]):
        return

    curr_fast = ma_fast.iloc[-1]
    prev_fast = ma_fast.iloc[-2]
    curr_slow = ma_slow.iloc[-1]
    prev_slow = ma_slow.iloc[-2]
    curr_rsi = float(rsi.iloc[-1])

    pos = api.get_pos(0)
    vol = api.get_param('volume', 1)
    ot = api.get_param('order_type', 'next_bar_open')
    ob = api.get_param('rsi_overbought', 72)
    os_level = api.get_param('rsi_oversold', 28)
    price = close.iloc[-1]

    golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
    death_cross = prev_fast >= prev_slow and curr_fast < curr_slow

    # 1~2：均线反手
    if pos > 0 and death_cross:
        api.log(f"[反手] 死叉 持多 {pos} 手 @ {price:.2f} → reverse_pos（平多开空）")
        api.reverse_pos(reason="死叉反手", order_type=ot, index=0)
        return
    if pos < 0 and golden_cross:
        api.log(f"[反手] 金叉 持空 {abs(pos)} 手 @ {price:.2f} → reverse_pos（平空开多）")
        api.reverse_pos(reason="金叉反手", order_type=ot, index=0)
        return

    # 3~4：RSI 仅平仓（多平 / 空平）
    if pos > 0 and not death_cross and curr_rsi >= ob:
        api.log(f"[多平] RSI={curr_rsi:.1f} 持多 {pos} 手 @ {price:.2f} → sell 全平")
        api.sell(order_type=ot, index=0)
        return
    if pos < 0 and not golden_cross and curr_rsi <= os_level:
        api.log(f"[空平] RSI={curr_rsi:.1f} 持空 {abs(pos)} 手 @ {price:.2f} → buycover 全平")
        api.buycover(order_type=ot, index=0)
        return

    # 5~6：空仓开仓
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
        'volume': 1,
        'fast': 5,
        'slow': 20,
        'rsi_period': 14,
        'rsi_overbought': 72,
        'rsi_oversold': 28,
        'order_type': 'next_bar_open',
    }

    config = get_config(
        RUN_MODE,
        symbol='rb888',             # 合约代码（支持 au2602, au888 等）
        start_date='2025-01-01',    # 回测开始日期
        end_date='2026-03-30',      # 回测结束日期
        kline_period='15m',         # K线周期: 1m/5m/15m/30m/1h/1d
        adjust_type='1',            # 复权: '0'不复权, '1'后复权, '2'前复权
        slippage_ticks=1,           # 滑点跳数（每跳=price_tick）
        initial_capital=100000,     # 初始资金（元）
        lookback_bars=500,          # 回溯K线窗口（IndicatorCache预热用）
        debug=False,                # 是否开启调试日志
            data_source_mode='data_server', # 'data_server'(远程,需API账号) 或 'local'(本地SQLite,无需账号) 注意:TICK回测必须用'local'
    )

    print("\n" + "=" * 60)
    print("混合开平仓（多开/空开 + 多平/空平 + 反手）")
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
