#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
专享策略33：全品种7因子截面策略（高性能版）- 5品种回测脚本
================================================================
策略核心架构：
  7 因子 (双流水线):
    Pipeline A (每根Bar): MOM, REV, VOL, VLM, AMP
    Pipeline B (调仓日):  IVOL, ISKEW (CAPM 残差分解)
  Z-Score → MGG (Market-Guided Gating) → EWMA 时序聚合
  滞后切换 (EnterRatio/KeepRatio) + 信号强度门槛过滤

回测品种（5个跨行业代表性品种）：
  rb888  - 螺纹钢  (黑色金属)
  au888  - 黄金    (贵金属)
  cu888  - 铜      (有色金属)
  m888   - 豆粕    (农产品)
  TA888  - PTA     (能化/化工)

运行方式:
  python run_策略33_5品种回测.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ssquant.backtest.unified_runner import UnifiedStrategyRunner, RunMode
from ssquant.config.trading_config import get_config
from vip33_opt_ssquant import _opt_strategy, initialize

# ================================================================
# 回测配置
# ================================================================
START_DATE      = '2022-01-01'
END_DATE        = '2026-04-30'
INITIAL_CAPITAL = 500000       # 初始资金（5品种，每品种约10万）

# 5个回测品种（覆盖黑色/贵金属/有色/农产品/能化 5大板块）
DATA_SOURCES = [
    {'symbol': 'rb888',  'kline_period': '1d', 'adjust_type': '1',
     'slippage_ticks': 1, 'capital_ratio': 1},   # 螺纹钢（黑色金属代表）

    {'symbol': 'au888',  'kline_period': '1d', 'adjust_type': '1',
     'slippage_ticks': 1, 'capital_ratio': 1},   # 黄金（贵金属代表）

    {'symbol': 'cu888',  'kline_period': '1d', 'adjust_type': '1',
     'slippage_ticks': 1, 'capital_ratio': 1},   # 铜（有色金属代表）

    {'symbol': 'm888',   'kline_period': '1d', 'adjust_type': '1',
     'slippage_ticks': 1, 'capital_ratio': 1},   # 豆粕（农产品代表）

    {'symbol': 'TA888',  'kline_period': '1d', 'adjust_type': '1',
     'slippage_ticks': 1, 'capital_ratio': 1},   # PTA（能化/化工代表）
]

# 4个核心可调参数
STRATEGY_PARAMS = {
    'MomWindow':         20,    # [10, 60]    主因子动量窗口
    'RebalancePeriod':   5,     # [3, 20]     调仓周期（越大交易越少）
    'EWMAAlpha':         0.30,  # [0.10, 0.70] EWMA 平滑系数（越小越稳）
    'MinSignalStrength': 0.30,  # [0, 1.0]   信号强度门槛（越大越严格）
}


def main():
    print("=" * 80)
    print("专享策略33：全品种7因子截面策略（高性能版 / IndicatorCache v2）")
    print("=" * 80)
    print(f"回测区间: {START_DATE} ~ {END_DATE}")
    print(f"初始资金: {INITIAL_CAPITAL:,} 元")
    print(f"回测品种: {[ds['symbol'] for ds in DATA_SOURCES]}")
    print(f"K线周期: 日线（1d）")
    print()
    print("4 个核心可调参数:")
    for k, v in STRATEGY_PARAMS.items():
        print(f"  {k:20s} = {v}")
    print("=" * 80 + "\n")

    # 构建配置
    config = get_config(
        RunMode.BACKTEST,
        start_date=START_DATE,
        end_date=END_DATE,
        initial_capital=INITIAL_CAPITAL,
        align_data=True,          # 截面策略必须对齐数据
        fill_method='ffill',
        lookback_bars=500,        # 预热 500 根 bar
        data_sources=DATA_SOURCES,
    )

    # 创建并运行回测
    runner = UnifiedStrategyRunner(mode=RunMode.BACKTEST)
    runner.set_config(config)

    try:
        results = runner.run(
            strategy=_opt_strategy,
            initialize=initialize,
            strategy_params=STRATEGY_PARAMS,
        )
        print("\n回测完成！结果已保存至 backtest_results/ 目录。")
        return results

    except KeyboardInterrupt:
        print("\n用户中断。")
        runner.stop()
    except Exception as e:
        print(f"\n运行出错: {e}")
        import traceback
        traceback.print_exc()
        runner.stop()


if __name__ == '__main__':
    main()
