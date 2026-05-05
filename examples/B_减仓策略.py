"""
减仓验证策略 - 演示部分平仓（sell/buycover 指定 volume），用于验证回测在分批减仓下的统计

策略逻辑：
  1. MA5 上穿 MA20 → 一次性开多 initial_lots 手；下穿 → 一次性开空 initial_lots 手
  2. 持多：RSI 超买且持仓 > min_lots → 减多 1 手（api.sell(volume=1)）
  3. 持多：MA5 下穿 MA20 → 平掉剩余全部多仓
  4. 空头对称：RSI 超卖且 |仓| > min_lots → 减空 1 手；金叉全平

不做金字塔加仓，仅「一次开满 + 分批减仓 + 趋势全平」。
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd

_state = {'bars_since_last_reduce': 0}

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
    api.log("减仓验证策略 初始化")
    api.log(f"  开仓手数: {api.get_param('initial_lots', 3)}（一次性开满）")
    api.log(f"  保留底仓: {api.get_param('min_lots', 1)} 手（低于此仅允许全部平仓）")
    api.log(f"  减仓间隔: {api.get_param('reduce_interval', 5)} 根K线")
    api.log(f"  RSI 超买/超卖: {api.get_param('rsi_overbought', 70)} / {api.get_param('rsi_oversold', 30)}")
    api.log("=" * 60)

def scale_out_strategy(api: StrategyAPI):
    klines = api.get_klines(0)
    rsi_period = api.get_param('rsi_period', 14)
    need = max(25, rsi_period + 5)
    if len(klines) < need:
        return

    close = klines['close']
    ma_fast = close.rolling(5).mean()
    ma_slow = close.rolling(20).mean()
    rsi = _rsi(close, rsi_period)

    if pd.isna(ma_fast.iloc[-1]) or pd.isna(ma_slow.iloc[-1]) or pd.isna(rsi.iloc[-1]):
        return

    curr_fast = ma_fast.iloc[-1]
    prev_fast = ma_fast.iloc[-2]
    curr_slow = ma_slow.iloc[-1]
    prev_slow = ma_slow.iloc[-2]
    curr_rsi = float(rsi.iloc[-1])

    pos = api.get_pos(0)
    initial_lots = api.get_param('initial_lots', 3)
    min_lots = api.get_param('min_lots', 1)
    reduce_interval = api.get_param('reduce_interval', 5)
    rsi_overbought = api.get_param('rsi_overbought', 70)
    rsi_oversold = api.get_param('rsi_oversold', 30)
    price = close.iloc[-1]

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
    print("减仓策略（一次开仓多手 + RSI 分批减仓）")
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
