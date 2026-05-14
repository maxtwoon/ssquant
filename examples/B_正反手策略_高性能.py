"""正反手示例策略 - 高性能版本（IndicatorCache v2）

与同目录下 `B_正反手策略.py` 行为完全一致。原版每根 Bar 重算 MA{fast} / MA{slow}；
本版在 initialize 钩子里把两根均线一次性注册到 IndicatorCache。

注意：本策略支持参数化均线周期（fast / slow），所以 initialize 阶段需要先读
strategy_params 再注册指标 — IndicatorCache 完全支持这种用法。

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

def initialize(api: StrategyAPI):
    api.log("=" * 60)
    api.log("正反手策略 初始化（高性能版 / IndicatorCache）")
    fast_n = api.get_param('fast', 5)
    slow_n = api.get_param('slow', 20)
    api.log(f"  开仓手数: {api.get_param('volume', 1)}（反手时与当前持仓手数一致）")
    api.log(f"  均线: MA{fast_n} / MA{slow_n}")
    api.log("=" * 60)

    ds_count = api.get_data_sources_count()
    for i in range(ds_count):
        api.register_indicator('ma_fast', _make_sma_func(fast_n), window=fast_n, index=i)
        api.register_indicator('ma_slow', _make_sma_func(slow_n), window=slow_n, index=i)

def reverse_demo_strategy(api: StrategyAPI):
    if api.get_idx(0) < 25:
        return

    fast_arr = api.get_indicator_array('ma_fast', window=2, index=0)
    slow_arr = api.get_indicator_array('ma_slow', window=2, index=0)
    if pd.isna(fast_arr[-1]) or pd.isna(slow_arr[-1]):
        return

    curr_fast = fast_arr[-1]
    prev_fast = fast_arr[-2]
    curr_slow = slow_arr[-1]
    prev_slow = slow_arr[-2]
    price = api.get_current_price(0)
    if price is None:
        return

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
        'volume': 1,                       # 开仓手数
        'fast': 5,                         # 快线周期
        'slow': 20,                        # 慢线周期
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
    print("正反手策略 - 高性能版本（IndicatorCache v2）")
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
