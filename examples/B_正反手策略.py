"""
正反手示例策略 — 演示 api.reverse_pos()：持仓为多头时遇空信号则「平多开空」，
空头时遇多信号则「平空开多」；空仓时仍用普通开多/开空。

与「先全平再反向开仓」相比，反手一笔完成换向，回测中会生成平多开空/平空开多相关成交
（或 next_bar 模式下拆成的平多+开空两腿，HTML 报告会合并显示反手图标）。

策略逻辑（MA5 / MA20）：
  - 金叉：若持空 → reverse_pos；若空仓 → 开多 1 手
  - 死叉：若持多 → reverse_pos；若空仓 → 开空 1 手
  - 已有多头再金叉、已有空头再死叉：不重复操作
"""
from ssquant.api.strategy_api import StrategyAPI
from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
import pandas as pd

def initialize(api: StrategyAPI):
    api.log("=" * 60)
    api.log("正反手策略 初始化")
    api.log(f"  开仓手数: {api.get_param('volume', 1)}（反手时与当前持仓手数一致）")
    api.log(f"  均线: MA{api.get_param('fast', 5)} / MA{api.get_param('slow', 20)}")
    api.log("=" * 60)

def reverse_demo_strategy(api: StrategyAPI):
    klines = api.get_klines(0)
    if len(klines) < 25:
        return

    close = klines['close']
    fast_n = api.get_param('fast', 5)
    slow_n = api.get_param('slow', 20)
    ma_fast = close.rolling(fast_n).mean()
    ma_slow = close.rolling(slow_n).mean()

    if pd.isna(ma_fast.iloc[-1]) or pd.isna(ma_slow.iloc[-1]):
        return

    curr_fast = ma_fast.iloc[-1]
    prev_fast = ma_fast.iloc[-2]
    curr_slow = ma_slow.iloc[-1]
    prev_slow = ma_slow.iloc[-2]
    price = close.iloc[-1]

    pos = api.get_pos(0)
    vol = api.get_param('volume', 1)
    ot = api.get_param('order_type', 'next_bar_open')

    golden_cross = prev_fast <= prev_slow and curr_fast > curr_slow
    death_cross = prev_fast >= prev_slow and curr_fast < curr_slow

    if golden_cross:
        if pos < 0:
            api.log(f"[金叉·反手] 价格 {price:.2f} 持空 {abs(pos)} 手 → reverse_pos（平空开多）")
            api.reverse_pos(reason="均线金叉反手", order_type=ot, index=0)
        elif pos == 0:
            api.log(f"[金叉] 价格 {price:.2f} → 开多 {vol} 手")
            api.buy(volume=vol, order_type=ot, index=0)

    if death_cross:
        if pos > 0:
            api.log(f"[死叉·反手] 价格 {price:.2f} 持多 {pos} 手 → reverse_pos（平多开空）")
            api.reverse_pos(reason="均线死叉反手", order_type=ot, index=0)
        elif pos == 0:
            api.log(f"[死叉] 价格 {price:.2f} → 开空 {vol} 手")
            api.sellshort(volume=vol, order_type=ot, index=0)

if __name__ == "__main__":
    from ssquant.config.trading_config import get_config

    # 运行模式: BACKTEST(回测) / SIMNOW(模拟盘) / REAL_TRADING(实盘交易)
    RUN_MODE = RunMode.BACKTEST

    strategy_params = {
        'volume': 1,
        'fast': 5,
        'slow': 20,
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
    print("正反手策略（reverse_pos 演示）")
    print("=" * 60)
    print(f"合约: {config['symbol']}, 周期: {config['kline_period']}")
    print(f"手数: {strategy_params['volume']}, 下单类型: {strategy_params['order_type']}")
    print("=" * 60 + "\n")

    runner = UnifiedStrategyRunner(mode=RUN_MODE)
    runner.set_config(config)

    try:
        runner.run(
            strategy=reverse_demo_strategy,
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
