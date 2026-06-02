"""
加仓验证策略 - 用于验证回测模块在加仓/部分平仓场景下的统计正确性

策略逻辑：
  1. MA5 上穿 MA20 → 开多 1 手
  2. 持多仓期间，每隔 add_interval 根K线 → 加仓 1 手（最多 max_lots 手）
  3. MA5 下穿 MA20 → 全部平仓
  4. 反向同理（开空 + 加空 + 平空）

这个策略会产生"多次开仓 → 一次性平仓"的交易序列，
用于验证回测统计（盈亏、胜率、权益曲线）在加仓场景下的正确性。
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd

_state = {'bars_since_last_add': 0}

def initialize(api: StrategyAPI):
    api.log("=" * 60)
    api.log("加仓验证策略 初始化")
    api.log(f"  最大持仓: {api.get_param('max_lots', 3)} 手")
    api.log(f"  加仓间隔: {api.get_param('add_interval', 10)} 根K线")
    api.log("=" * 60)

def pyramid_test_strategy(api: StrategyAPI):
    klines = api.get_klines(0)
    if len(klines) < 25:
        return

    close = klines['close']
    ma_fast = close.rolling(5).mean()
    ma_slow = close.rolling(20).mean()

    if pd.isna(ma_fast.iloc[-1]) or pd.isna(ma_slow.iloc[-1]):
        return

    curr_fast = ma_fast.iloc[-1]
    prev_fast = ma_fast.iloc[-2]
    curr_slow = ma_slow.iloc[-1]
    prev_slow = ma_slow.iloc[-2]

    pos = api.get_pos(0)
    max_lots = api.get_param('max_lots', 3)
    add_interval = api.get_param('add_interval', 10)
    price = close.iloc[-1]

    golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
    death_cross = prev_fast >= prev_slow and curr_fast < curr_slow

    if pos == 0:
        _state['bars_since_last_add'] = 0
        if golden_cross:
            api.log(f"[金叉] 价格 {price:.2f} → 开多 1 手")
            api.buy(volume=1, order_type='next_bar_open', index=0)
            _state['bars_since_last_add'] = 0
        elif death_cross:
            api.log(f"[死叉] 价格 {price:.2f} → 开空 1 手")
            api.sellshort(volume=1, order_type='next_bar_open', index=0)
            _state['bars_since_last_add'] = 0

    elif pos > 0:
        if death_cross:
            api.log(f"[死叉] 价格 {price:.2f} → 平多 {pos} 手")
            api.sell(order_type='next_bar_open', index=0)
            _state['bars_since_last_add'] = 0
        elif pos < max_lots:
            _state['bars_since_last_add'] += 1
            if _state['bars_since_last_add'] >= add_interval and curr_fast > curr_slow:
                api.log(f"[加仓] 价格 {price:.2f} → 加多 1 手 (当前 {pos} 手)")
                api.buy(volume=1, order_type='next_bar_open', index=0)
                _state['bars_since_last_add'] = 0

    elif pos < 0:
        if golden_cross:
            api.log(f"[金叉] 价格 {price:.2f} → 平空 {abs(pos)} 手")
            api.buycover(order_type='next_bar_open', index=0)
            _state['bars_since_last_add'] = 0
        elif abs(pos) < max_lots:
            _state['bars_since_last_add'] += 1
            if _state['bars_since_last_add'] >= add_interval and curr_fast < curr_slow:
                api.log(f"[加仓] 价格 {price:.2f} → 加空 1 手 (当前 {abs(pos)} 手)")
                api.sellshort(volume=1, order_type='next_bar_open', index=0)
                _state['bars_since_last_add'] = 0

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'max_lots': 3,
        'add_interval': 10,
    }

    config = get_config(RUN_MODE,
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
    print("加仓验证策略")
    print("=" * 60)
    print(f"合约: {config['symbol']}, 周期: {config['kline_period']}")
    print(f"最大持仓: {strategy_params['max_lots']} 手")
    print(f"加仓间隔: {strategy_params['add_interval']} 根K线")
    print("=" * 60 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=pyramid_test_strategy,
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
