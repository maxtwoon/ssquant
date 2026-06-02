#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
策略20 LLM辅助交易策略 - 回测脚本
运行方式: python run_策略20_LLM回测.py
"""

import sys
import os

# 确保能找到 ssquant 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ssquant.backtest.multi_source_backtest import MultiSourceBacktester
from 策略20_LLM辅助交易策略 import strategy_llm, initialize

# ============================================================
# 回测配置
# ============================================================
SYMBOL       = 'au888'       # 品种（黄金期货主力连续）
KLINE_PERIOD = '1h'          # K线周期（1h 日内 LLM信号质量较好）
START_DATE   = '2022-01-01'
END_DATE     = '2024-12-31'
INITIAL_CAP  = 100000        # 初始资金（元）

# 策略参数
STRATEGY_PARAMS = {
    'fast_ma'      : 20,    # 快均线
    'slow_ma'      : 60,    # 慢均线
    'rsi_period'   : 14,    # RSI周期
    'atr_period'   : 14,    # ATR周期
    'atr_stop_mult': 2.0,   # ATR止损倍数
    'llm_conf_thr' : 0.55,  # LLM信心阈值（回测时适当调低）
    'vol_ma_period': 20,    # 量能均线周期
}

# ============================================================
# 合约参数（黄金 au888）
# ============================================================
SYMBOL_CONFIG = {
    'kline_period'       : KLINE_PERIOD,
    'adjust_type'        : '1',       # 后复权
    'start_date'         : START_DATE,
    'end_date'           : END_DATE,
    'initial_capital'    : INITIAL_CAP,
    'commission'         : 0.0001,    # 万分之一
    'margin_rate'        : 0.09,      # 9% 保证金
    'contract_multiplier': 1000,      # 黄金1000克/手
    'price_tick'         : 0.02,      # 最小变动0.02元/克
    'slippage_ticks'     : 1,
}

# ============================================================
# 运行回测
# ============================================================
def main():
    print("=" * 65)
    print("策略20：LLM辅助多因子交易策略 — 回测开始")
    print(f"品种: {SYMBOL}  周期: {KLINE_PERIOD}")
    print(f"时间: {START_DATE} ~ {END_DATE}")
    print(f"初始资金: {INITIAL_CAP:,} 元")
    print(f"策略参数: {STRATEGY_PARAMS}")
    print("=" * 65)

    backtester = MultiSourceBacktester()

    backtester.set_base_config({
        'use_cache'        : True,
        'save_data'        : True,
        'align_data'       : False,
        'debug'            : False,
        'data_source_mode' : 'data_server',  # 使用远程数据
        'lookback_bars'    : 0,
    })

    backtester.add_symbol_config(SYMBOL, SYMBOL_CONFIG)

    results = backtester.run(
        strategy    = strategy_llm,
        initialize  = initialize,
        strategy_params = STRATEGY_PARAMS,
    )

    # 打印核心绩效
    print("\n" + "=" * 65)
    print("回测结果汇总")
    print("=" * 65)
    for ds_key, ds_result in results.items():
        if not isinstance(ds_result, dict):
            continue
        print(f"\n数据源: {ds_key}")
        metrics = [
            ('总交易次数',  'total_trades'),
            ('胜率',        'win_rate'),
            ('盈亏比',      'profit_factor'),
            ('总净盈亏',    'total_profit'),
            ('年化收益率',  'annual_return'),
            ('最大回撤',    'max_drawdown'),
            ('夏普比率',    'sharpe_ratio'),
        ]
        for label, key in metrics:
            val = ds_result.get(key, ds_result.get('performance', {}).get(key, 'N/A'))
            if isinstance(val, float):
                print(f"  {label}: {val:.4f}")
            else:
                print(f"  {label}: {val}")

    print("\n回测完成！查看 backtest_results/ 目录获取完整报告。")
    return results


if __name__ == '__main__':
    main()
